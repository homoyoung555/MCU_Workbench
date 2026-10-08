"""Execute compiled COMMIT field writes against complete Page Images."""

from dataclasses import dataclass
from typing import Mapping, Tuple

from program_gen.core.addr_map import AddrMapCatalog
from program_gen.core.page_image import FieldTarget, FieldWrite, PageImageStore
from program_gen.core.persistence_recipe import PersistenceFieldWrite, PersistenceOperation


class CommitExecutionError(ValueError):
    """A typed COMMIT value cannot be resolved or applied."""


@dataclass(frozen=True)
class PatternStorageWord:
    page: str
    register: str
    storage_word: int


@dataclass(frozen=True)
class CommitFlush:
    consumer: str
    pages: Tuple[str, ...]
    words: Tuple[PatternStorageWord, ...]
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CommitExecutionPlan:
    flushes: Tuple[CommitFlush, ...]
    consumers: Tuple[str, ...]


class CommitExecutor:
    """Accumulate consecutive COMMITs and flush once before a Pattern consumer."""

    def __init__(
        self,
        page_images: PageImageStore,
        catalog: AddrMapCatalog,
        *,
        values: Mapping[str, int] | None = None,
        step: int | None = None,
    ) -> None:
        self._page_images = page_images
        self._catalog = catalog
        self._values = dict(values or {})
        self._step = step
        self._pending: dict[
            tuple[str, str, int, int], tuple[PersistenceFieldWrite, int, str]
        ] = {}
        self._warnings: list[str] = []

    def add_commit(
        self,
        writes: Tuple[PersistenceFieldWrite, ...],
        *,
        source: str = "EXPLICIT",
    ) -> None:
        source_kind = str(source).strip().upper()
        if source_kind not in ("DEFAULT", "EXPLICIT"):
            raise CommitExecutionError(f"COMMIT source 不支持 {source!r}")
        resolved = tuple((write, self._resolve_value(write)) for write in writes)
        for write, resolved_value in resolved:
            key = (
                write.page.casefold(), write.register.casefold(), write.lsb, write.width
            )
            previous = self._pending.get(key)
            if previous is not None and previous[2] == "DEFAULT" and source_kind == "EXPLICIT":
                self._warnings.append(
                    f"字段 {write.field} 的默认 COMMIT 值被显式 COMMIT 覆盖"
                )
            self._pending[key] = (write, resolved_value, source_kind)

    def flush_before(self, consumer: str) -> CommitFlush:
        field_writes = tuple(
            FieldWrite(
                target=FieldTarget(
                    field=write.field,
                    page=write.page,
                    register=write.register,
                    lsb=write.lsb,
                    width=write.width,
                    destination="PATTERN",
                ),
                value=value,
            )
            for write, value, _source in self._pending.values()
        )
        pages = self._page_images.commit(field_writes)
        words = []
        seen = set()
        for write, _value, _source in self._pending.values():
            key = (write.page, write.register)
            if key in seen:
                continue
            seen.add(key)
            register = self._catalog.resolve_register(write.register)
            real_value = self._page_images.register_value(write.page, write.register)
            words.append(PatternStorageWord(
                page=write.page,
                register=write.register,
                storage_word=register.storage_word(real_value),
            ))
        self._pending.clear()
        warnings = tuple(self._warnings)
        self._warnings.clear()
        return CommitFlush(
            consumer=str(consumer), pages=pages, words=tuple(words), warnings=warnings
        )

    def _resolve_value(self, write: PersistenceFieldWrite) -> int:
        value = write.value
        if value.kind == "DECIMAL":
            return int(value.token, 10)
        if value.kind == "HEX":
            return int(value.token, 16)
        if value.kind == "BINARY":
            return int(value.token, 2)
        if value.kind == "STEP" and self._step is not None:
            return int(self._step)
        if value.kind == "VARIABLE" and value.token in self._values:
            return int(self._values[value.token])
        raise CommitExecutionError(
            f"COMMIT 字段 {write.field} 的值 {value.token!r} 没有可用来源"
        )


_PAGE_PATTERN_CONSUMERS = frozenset(("PGMOTP", "CHECKOTP", "RUN", "NMLOOP"))


def execute_commit_operations(
    operations: Tuple[PersistenceOperation, ...],
    page_images: PageImageStore,
    catalog: AddrMapCatalog,
    *,
    values: Mapping[str, int] | None = None,
    step: int | None = None,
) -> CommitExecutionPlan:
    """Merge COMMITs and flush them immediately before a page Pattern consumer."""
    executor = CommitExecutor(page_images, catalog, values=values, step=step)
    flushes = []
    consumers = []
    pending = False
    for operation in operations:
        if operation.module == "COMMIT":
            executor.add_commit(
                operation.field_writes,
                source=operation.commit_source or "EXPLICIT",
            )
            pending = pending or bool(operation.field_writes)
            continue
        consumers.append(operation.module)
        if operation.module in _PAGE_PATTERN_CONSUMERS and pending:
            flushes.append(executor.flush_before(operation.module))
            pending = False
    if pending:
        flushes.append(executor.flush_before("END"))
    return CommitExecutionPlan(
        flushes=tuple(flushes), consumers=tuple(consumers)
    )


def validate_trimdata_recipe_contract(
    node: str, modules: Tuple[str, ...]
) -> None:
    """Validate the two agreed Trimdata persistence node contracts."""
    canonical_node = str(node).strip().casefold()
    canonical_modules = tuple(str(module).strip().upper() for module in modules)
    if canonical_node == "trimdata_write":
        allowed = {
            ("COMMIT", "PGMOTP"),
            ("COMMIT", "SETVPOSP", "PGMOTP"),
        }
    elif canonical_node == "trimdata_rewrite":
        allowed = {("COMMIT", "PGMOTP")}
    else:
        raise CommitExecutionError(f"不支持 Trimdata Recipe contract {node!r}")
    if canonical_modules not in allowed:
        expected = " 或 ".join("→".join(recipe) for recipe in sorted(allowed))
        actual = "→".join(canonical_modules) or "<空>"
        raise CommitExecutionError(
            f"{node} Recipe 必须是 {expected}，实际 {actual}"
        )
