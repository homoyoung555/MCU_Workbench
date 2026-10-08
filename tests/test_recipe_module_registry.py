"""Public Interface tests for native Recipe Module registration."""

from __future__ import annotations

import unittest

from program_gen.core.run_pattern import (
    PatternResourceRef,
    PatternSpan,
    RunPatternPlan,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.recipe_module_registry import (
    RecipeModuleEmission,
    RecipeModulePlugin,
    RecipeModuleRegistry,
    RecipeModuleRegistryError,
)


class RegisteredRecipeModuleTests(unittest.TestCase):
    def test_registered_run_routes_one_typed_plan_to_both_platform_adapters(self):
        plan = RunPatternPlan(
            pattern=PatternResourceRef(
                name="enter_fbist_mode",
                logical_identity="pattern:enter_fbist_mode",
                ordered_labels=("START", "END"),
            ),
            span=PatternSpan.full(),
            timing_profile="TS_5MHZ",
        )

        chroma = NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", plan, "chroma")
        s100 = NATIVE_RECIPE_MODULE_REGISTRY.emit("run", plan, "S100")

        self.assertIsInstance(chroma, RecipeModuleEmission)
        self.assertIsInstance(s100, RecipeModuleEmission)
        self.assertEqual(
            NATIVE_RECIPE_MODULE_REGISTRY.registered_modules,
            (
                "MARGIN_TEST", "VT_TEST", "NM_TEST", "READID", "CHECKID", "BUILDUID",
                "RUN", "SRAM_CAPTURE", "ENTER", "JUDGE", "EXPORT", "SETVPOSP", "DAC_ADJ",
                "DAC_WRITE", "COMMIT", "BUILDMAP", "NMLOOP",
                "READOTPMAP", "LOADMAP", "CHECKOTP", "PGMOTP",
            ),
        )
        self.assertEqual(
            chroma.statements,
            (
                "  TEST_NUM++;",
                '  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";',
                "  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);",
                "",
            ),
        )
        self.assertEqual(
            s100.statements,
            (
                "\tRUN_PATTERN(enter_fbist_mode:START,"
                "enter_fbist_mode:END,1,TS_5MHZ);",
            ),
        )


class RecipeModuleRegistryInvariantTests(unittest.TestCase):
    def test_duplicate_module_registration_is_blocking(self):
        plugin = RecipeModulePlugin(
            name="RUN",
            plan_type=RunPatternPlan,
            adapters=(("chroma", lambda plan: plan), ("s100", lambda plan: plan)),
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            RecipeModuleRegistry((plugin, plugin))

        self.assertEqual(raised.exception.code, "RM.REGISTRY.DUPLICATE")

    def test_unregistered_module_is_blocking(self):
        with self.assertRaises(RecipeModuleRegistryError) as raised:
            NATIVE_RECIPE_MODULE_REGISTRY.emit(
                "UNKNOWN_MODULE", object(), "chroma"
            )

        self.assertEqual(raised.exception.code, "RM.REGISTRY.UNREGISTERED")

    def test_module_plan_type_mismatch_is_blocking_before_adapter_execution(self):
        with self.assertRaises(RecipeModuleRegistryError) as raised:
            NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", object(), "chroma")

        self.assertEqual(raised.exception.code, "RM.REGISTRY.PLAN_INVALID")

    def test_registration_requires_both_platform_adapters(self):
        plugin = RecipeModulePlugin(
            name="RUN",
            plan_type=RunPatternPlan,
            adapters=(("chroma", lambda plan: plan),),
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            RecipeModuleRegistry((plugin,))

        self.assertEqual(raised.exception.code, "RM.REGISTRY.ADAPTER_MISSING")

    def test_adapter_must_return_the_common_module_emission(self):
        class FakePlan:
            pass

        plugin = RecipeModulePlugin(
            name="FAKE",
            plan_type=FakePlan,
            adapters=(
                ("chroma", lambda plan: object()),
                ("s100", lambda plan: object()),
            ),
        )
        registry = RecipeModuleRegistry((plugin,))

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            registry.emit("FAKE", FakePlan(), "chroma")

        self.assertEqual(raised.exception.code, "RM.REGISTRY.RESULT_INVALID")

    def test_duplicate_platform_adapter_registration_is_blocking(self):
        plugin = RecipeModulePlugin(
            name="RUN",
            plan_type=RunPatternPlan,
            adapters=(
                ("chroma", lambda plan: plan),
                ("CHROMA", lambda plan: plan),
                ("s100", lambda plan: plan),
            ),
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            RecipeModuleRegistry((plugin,))

        self.assertEqual(raised.exception.code, "RM.REGISTRY.ADAPTER_DUPLICATE")

    def test_unregistered_platform_is_blocking(self):
        plan = RunPatternPlan(
            pattern=PatternResourceRef(
                name="enter_fbist_mode",
                logical_identity="pattern:enter_fbist_mode",
                ordered_labels=("START", "END"),
            ),
            span=PatternSpan.full(),
            timing_profile="TS_5MHZ",
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", plan, "teradyne")

        self.assertEqual(raised.exception.code, "RM.REGISTRY.PLATFORM_UNREGISTERED")

    def test_module_registration_requires_a_name(self):
        plugin = RecipeModulePlugin(
            name=" ",
            plan_type=RunPatternPlan,
            adapters=(
                ("chroma", lambda plan: plan),
                ("s100", lambda plan: plan),
            ),
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            RecipeModuleRegistry((plugin,))

        self.assertEqual(raised.exception.code, "RM.REGISTRY.NAME_EMPTY")

    def test_module_registration_requires_a_plan_type(self):
        plugin = RecipeModulePlugin(
            name="RUN",
            plan_type="RunPatternPlan",
            adapters=(
                ("chroma", lambda plan: plan),
                ("s100", lambda plan: plan),
            ),
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            RecipeModuleRegistry((plugin,))

        self.assertEqual(raised.exception.code, "RM.REGISTRY.PLAN_TYPE_INVALID")

    def test_module_registration_requires_callable_adapters(self):
        plugin = RecipeModulePlugin(
            name="RUN",
            plan_type=RunPatternPlan,
            adapters=(
                ("chroma", lambda plan: plan),
                ("s100", object()),
            ),
        )

        with self.assertRaises(RecipeModuleRegistryError) as raised:
            RecipeModuleRegistry((plugin,))

        self.assertEqual(raised.exception.code, "RM.REGISTRY.ADAPTER_INVALID")


if __name__ == "__main__":
    unittest.main()
