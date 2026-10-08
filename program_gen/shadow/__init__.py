"""Shadow-slice STANDARD_TRIM: dual-platform native slice, not registered.

The shadow slice compiles one typed TrimSpec + canonical schedule + row-bound
export plan into closed Chroma and S100 contributions with real fragments,
closes a RenderPlan through the shared ProgramAssembler, and stages a shadow
artifact set.  It never registers into the formal native registry
(``PlatformRenderPlanner`` family renderers / business contribution fan-out)
and never fabricates providers: every symbol requirement is satisfied by a
real fragment, seed resource, or declared runtime global.
"""
