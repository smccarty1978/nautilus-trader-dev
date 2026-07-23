# Study invalidated

The results in this directory used canonical checkpoint artifact
`d6e5b71e6244cd7ed19161862211e1c3f8bc668c1c7db7cd7fe81b5d25de8121`.
That artifact's MFE/MAE and extremum timestamps were invalid due to a completed-
row range-query bug. Do not use the PnL, stopout, trade, summary, or report
outputs until this study is explicitly rerun against repaired artifact
`97afa92a737749fe217a217f87f8ade25ef39cc14b18ad47f8a48b77f0a595c3`.
