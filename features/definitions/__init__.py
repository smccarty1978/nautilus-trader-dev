"""Feature definition modules -- the catalogue side of the feature registration boundary.

Every module in this package is DATA: it declares feature definitions and nothing else.  None
of them is imported by the resolver, by the host, by the outcome guard or by the output
manager; ``features.registry`` discovers them through the declared capability index
(``research_workflow/capabilities_index.d/feature_definitions.yaml``) and imports them
by dotted path.  That is what makes "adding a definition cannot change how an existing binding
resolves" a fact about the import graph rather than a claim.

Deliberately empty of imports: a package init that re-exported its submodules would put every
definition back on the reachable surface of everything that touches the package.
"""
