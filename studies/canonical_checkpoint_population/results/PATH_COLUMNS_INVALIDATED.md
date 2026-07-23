# Path columns invalidated — 2026-07-22

The artifact with SHA-256
`d6e5b71e6244cd7ed19161862211e1c3f8bc668c1c7db7cd7fe81b5d25de8121`
contains invalid path extrema. Its vectorized range query continued processing
rows after their individual intervals had completed, allowing extrema from
ancestor nodes outside the requested slice to overwrite valid results.

Do not use any MFE, MAE, extremum-timestamp, or derived path-policy output from
that artifact or its CSV exports. Identification, scoring, percentile,
first-signal, and flip-timing fields were not computed by the faulty range query.

The repaired replacement artifact is now accepted with SHA-256
`97afa92a737749fe217a217f87f8ade25ef39cc14b18ad47f8a48b77f0a595c3`.
It passed pre-execution and completion audits with zero findings, exhaustive
synthetic range tests, and an independent direct replay of 28,672 raw intervals.
The combined and 2024/2025 CSV exports were regenerated from that artifact.
