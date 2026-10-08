"""Compile persistence Recipe operations into a platform-neutral plan."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence, Tuple

from flow_recipe import ExecutableFlowRow, RecipeValueToken
from program_gen.core.addr_map import AddrMapCompileError


class PersistenceCompileError(ValueError):
    """A persistence Recipe violates an explicit producer/consumer contract."""


class FieldCatalog(Protocol):
    @property
    def pages(self) -> tuple[str, ...]: ...

    def resolve_fields(self, name: str): ...


@dataclass(frozen=True)
class PersistenceOperation:
    module: str
    excel_row: int
    requested_pages: Tuple[str, ...]
    effective_pages: Tuple[str, ...]
    field_writes: Tuple["PersistenceFieldWrite", ...] = ()
    commit_source: str | None = None


@dataclass(frozen=True)
class PersistenceFieldWrite:
    field: str
    page: str
    register: str
    lsb: int
    width: int
    value: RecipeValueToken


@dataclass(frozen=True)
class PersistencePlan:
    cp: str
    operations: Tuple[PersistenceOperation, ...]


@dataclass(frozen=True)
class PersistenceRowPlan:
    cp: str
    excel_row: int
    operations: Tuple[PersistenceOperation, ...]

    def operation(self, module: str) -> PersistenceOperation | None:
        name = str(module).strip().upper()
        return next((operation for operation in self.operations
                     if operation.module == name), None)


@dataclass(frozen=True)
class PersistencePlanSet:
    rows: Mapping[int, PersistenceRowPlan]

    def for_row(self, flow_row_index: int) -> PersistenceRowPlan | None:
        return self.rows.get(flow_row_index)


_PERSISTENCE_MODULES = frozenset((
    "BUILDMAP", "READOTPMAP", "LOADMAP", "SETVPOSP", "NMLOOP",
    "CHECKOTP", "COMMIT", "PGMOTP", "BUILDUID",
))


def compile_persistence_plan_set(
    flow_frame,
    recipe_rows: Mapping[int, ExecutableFlowRow],
    catalog: FieldCatalog,
    *,
    node_default_pages: Mapping[int, Iterable[str]] | None = None,
    node_default_bindings: Mapping[int, tuple] | None = None,
    node_write_pages: Mapping[int, tuple[str, ...]] | None = None,
) -> PersistencePlanSet:
    """Compile CP flow state once, then expose each writer row's operations."""
    from dataclasses import replace

    compiled: dict[int, PersistenceRowPlan] = {}
    cps = tuple(dict.fromkeys(
        row.flow.cp for row in recipe_rows.values()
        if any(operation.name in _PERSISTENCE_MODULES
               for operation in row.operations)
    ))
    default_pages = dict(node_default_pages or {})
    default_bindings = dict(node_default_bindings or {})
    for cp in cps:
        selected = tuple(
            replace(row, operations=tuple(
                operation for operation in row.operations
                if operation.name in _PERSISTENCE_MODULES
            ))
            for _index, row in sorted(recipe_rows.items())
            if row.flow.cp == cp and any(
                operation.name in _PERSISTENCE_MODULES
                for operation in row.operations
            )
        )
        row_pages = {
            row.flow.excel_row: tuple(default_pages.get(
                row.flow.excel_row, catalog.pages
            ))
            for row in selected
        }
        plan = compile_persistence_plan(
            selected,
            catalog,
            node_default_pages=row_pages,
            node_default_bindings=default_bindings,
            node_write_pages=node_write_pages,
        )
        for row in selected:
            index = row.flow.excel_row - 2
            operations = tuple(operation for operation in plan.operations
                               if operation.excel_row == row.flow.excel_row)
            compiled[index] = PersistenceRowPlan(cp, row.flow.excel_row, operations)
    return PersistencePlanSet(compiled)


def compile_persistence_plan(
    rows: Sequence[ExecutableFlowRow],
    catalog: FieldCatalog,
    *,
    node_default_pages: Mapping[int, Iterable[str]] | None = None,
    node_default_bindings: Mapping[int, tuple] | None = None,
    node_write_pages: Mapping[int, tuple[str, ...]] | None = None,
) -> PersistencePlan:
    """Compile one CP's ordered Recipe rows without inserting missing modules."""
    if not rows:
        raise PersistenceCompileError("PersistencePlan 至少需要一行 FLOW")
    cps = tuple(dict.fromkeys(row.flow.cp for row in rows))
    if len(cps) != 1:
        raise PersistenceCompileError("一个 PersistencePlan 只能包含同一道 CP")
    default_pages = node_default_pages or {}
    default_bindings = node_default_bindings or {}

    complete_pages: set[str] = set()
    captured_pages: set[str] = set()
    loaded_pages: set[str] = set()
    builduid_count = 0
    operations = []
    for row in rows:
        row_pages = _canonical_pages(
            default_pages.get(row.flow.excel_row, ()), catalog.pages
        )
        for call in row.operations:
            requested = _requested_pages(call.name, call.argument, row_pages)
            if call.name == "PGMOTP" and call.argument is None and row.flow.flow_type == "uid":
                requested = ("uid",)
            if (
                call.name in ("LOADMAP", "PGMOTP") and call.argument is None
                and row.flow.excel_row in (node_write_pages or {})
            ):
                requested = _canonical_pages(node_write_pages[row.flow.excel_row], catalog.pages)
            effective = requested
            field_writes: Tuple[PersistenceFieldWrite, ...] = ()
            commit_source = None
            if call.name == "BUILDUID":
                builduid_count += 1
                if builduid_count > 1:
                    raise PersistenceCompileError(
                        f"FLOW row {row.flow.excel_row}: BUILDUID 每道 CP 最多一次"
                    )
            if call.name == "BUILDMAP":
                complete_pages.update(requested)
            elif call.name == "READOTPMAP":
                effective = tuple(page for page in requested if page not in captured_pages)
                captured_pages.update(effective)
                complete_pages.update(effective)
            elif call.name == "LOADMAP":
                missing = tuple(page for page in requested if page not in complete_pages)
                if missing:
                    raise PersistenceCompileError(
                        f"FLOW row {row.flow.excel_row}: LOADMAP 需要前序完整 Page Image: "
                        + ", ".join(missing)
                    )
                loaded_pages.update(requested)
            elif call.name == "COMMIT":
                commit_source = "EXPLICIT" if call.assignments else "DEFAULT"
                assignments = (
                    call.assignments
                    if call.assignments
                    else tuple(default_bindings.get(row.flow.excel_row, ()))
                )
                if row.flow.flow_type != "shmoo" and any(
                    assignment.value.kind == "STEP" for assignment in assignments
                ):
                    raise PersistenceCompileError(
                        f"FLOW row {row.flow.excel_row}: COMMIT 的 STEP 只能用于 type=shmoo"
                    )
                field_writes = _compile_explicit_writes(assignments, catalog)
                if row.flow.flow_type == "uid":
                    uid_writes = tuple(write for write in field_writes if write.page.casefold() == "uid")
                    missing_fields = {write.field for write in field_writes} - {write.field for write in uid_writes}
                    if call.assignments and missing_fields:
                        raise PersistenceCompileError(
                            f"FLOW row {row.flow.excel_row}: UID COMMIT 字段不在 UID 页: "
                            + ", ".join(sorted(missing_fields))
                        )
                    field_writes = uid_writes
                commit_pages = tuple(dict.fromkeys(write.page for write in field_writes))
                missing = tuple(page for page in commit_pages if page not in complete_pages)
                if missing:
                    raise PersistenceCompileError(
                        f"FLOW row {row.flow.excel_row}: COMMIT 需要前序完整 Page Image: "
                        + ", ".join(missing)
                    )
                effective = commit_pages
                loaded_pages.update(commit_pages)
            elif call.name in ("CHECKOTP", "PGMOTP"):
                missing = tuple(page for page in requested if page not in loaded_pages)
                if missing:
                    raise PersistenceCompileError(
                        f"FLOW row {row.flow.excel_row}: {call.name} 需要前序完整 Program/Read Pattern: "
                        + ", ".join(missing)
                    )
            operations.append(PersistenceOperation(
                module=call.name,
                excel_row=row.flow.excel_row,
                requested_pages=requested,
                effective_pages=effective,
                field_writes=field_writes,
                commit_source=commit_source,
            ))
    return PersistencePlan(cp=cps[0], operations=tuple(operations))


def _canonical_pages(pages: Iterable[str], catalog_pages: Iterable[str]) -> Tuple[str, ...]:
    known = {str(page).casefold(): str(page) for page in catalog_pages}
    result = []
    for page in pages:
        key = str(page).strip().casefold()
        if key not in known:
            raise PersistenceCompileError(f"ADDR_MAP 中不存在页面 {page}")
        if known[key] not in result:
            result.append(known[key])
    return tuple(result)


def _requested_pages(
    module: str, argument: str | None, defaults: Tuple[str, ...]
) -> Tuple[str, ...]:
    if argument is None:
        if module in ("CHECKOTP", "PGMOTP"):
            return tuple(page for page in defaults if page.casefold() != "uid")
        return defaults
    if argument == "UID":
        return ("uid",)
    raise PersistenceCompileError(f"不支持页面参数 {argument}")


def _compile_explicit_writes(assignments, catalog: FieldCatalog) -> Tuple[PersistenceFieldWrite, ...]:
    writes = []
    for assignment in assignments:
        try:
            fields = catalog.resolve_fields(assignment.field)
        except AddrMapCompileError as exc:
            raise PersistenceCompileError(str(exc)) from exc
        for field in fields:
            constant = _constant_value(assignment.value)
            if constant is not None and constant >= (1 << field.width):
                raise PersistenceCompileError(
                    f"字段 {field.name} 是 {field.width} bit，不能写入 {constant}"
                )
            writes.append(PersistenceFieldWrite(
                field=field.name,
                page=field.page,
                register=field.register,
                lsb=field.lsb,
                width=field.width,
                value=assignment.value,
            ))
    return tuple(writes)


def _constant_value(value: RecipeValueToken) -> int | None:
    if value.kind == "DECIMAL":
        return int(value.token, 10)
    if value.kind == "HEX":
        return int(value.token, 16)
    if value.kind == "BINARY":
        return int(value.token, 2)
    return None
