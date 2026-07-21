PRE-FLIP D10 REVERSAL STUDY

PRIMARY CONTRACT:
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT

VALIDATION STATUS:
1-SECOND OHLC RESEARCH SIMULATION; NOT NT-NATIVE EXECUTABLE VALIDATION

BEST POLICY:
NONE (no test-set optimization)

2025 EV LIFT VS FLIP-TO-FLIP BASELINE:
-8.1342 to -3.7615

2026 EV LIFT VS FLIP-TO-FLIP BASELINE:
16.0856 to 21.3184

2025 STOP-OUT BEFORE FLIP RATE:
0.2835 to 0.5086

2026 STOP-OUT BEFORE FLIP RATE:
0.2751 to 0.5099

2025 NEW-REGIME D10 EXIT RATE:
0.1841 to 0.7645

2026 NEW-REGIME D10 EXIT RATE:
0.1806 to 0.7849

2025 OPPOSITE-FLIP FALLBACK EXIT RATE:
0.0812 to 0.2355

2026 OPPOSITE-FLIP FALLBACK EXIT RATE:
0.0748 to 0.2151

PERCENT OF VALIDLY SCORED REGIMES THAT EVER REACH D10:
77.98%

AVERAGE PRE-FLIP PNL:
$0.44

AVERAGE POST-FLIP PNL:
$-5.23

D10 FRONT-RUN ENTRY ADVANTAGE VS WAITING FOR FLIP:
$-1.82 (-0.018 ATR)

MATCHED PLACEBO P-VALUE:
0.0004 to 0.0846 across frozen cells

VERDICT:
CLOSE

1. Executive summary

Primary: explicit next-open OHLC research simulation. Stop wins same-bar ties. Contract 3 is sensitivity only. No 2026 parameter selection. Headline PnL and front-run statistics use primary P1/P3 trades only.

2. Exact strategy and policy definitions

See SPEC.md and config.yaml.

3. Frozen D10 threshold definition

Absolute Jan-Feb 2025 validation-frozen W4 90th percentile: 0.618327857739.

4. Entry timing audit

See audit/entry_timing_audit.parquet. Extended >60s gap cells total 650 trade rows; maximum delay 262029s. These are first-available opens across documented market-data closures.

5. Stop execution audit

Entry-bar stop enabled; worse-open gap rule; exact intrabar touch order unknown.

6. Score and regime-ID reset audit

See audit/score_regime_id_audit.parquet.

7. Regime-level D10 coverage

 regimes  validly_scored  score_unavailable  valid_scored_ever_d10  valid_scored_never_d10  d10_same_timestamp_as_end  right_censored
   31844           31810                 34                  24805                    7005                          0               0

8. D10 entry diagnostics

See forward_reversal_diagnostics.parquet.

9. Pre-flip versus post-flip PnL decomposition

See pnl_decomposition.parquet and preflip_vs_wait_for_flip.parquet.

10. Stop sensitivity

                       execution_contract  year policy  stop_atr_mult  trade_count  censored_count  win_rate     gross_pnl        net_pnl  ev_per_trade  profit_factor  maximum_drawdown  median_trade   p10_trade  p90_trade  stop_out_before_flip_rate  flip_confirmation_rate  post_confirmation_stop_rate  d10_exit_rate  opposite_flip_fallback_exit_rate  same_bar_tie_count  same_bar_tie_rate
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P1            0.5        15019               0  0.157734 -90646.463215 -240836.463215    -16.035453       0.803625    -263686.941597    -65.000000 -166.961601      125.0                   0.505693                0.494307                     0.296291       0.000000                          0.198016                  32           0.002131
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P1            1.0        12952               0  0.245290 -65129.756405 -194649.756405    -15.028548       0.876514    -251618.756726    -90.000000 -280.525433      274.5                   0.363342                0.636658                     0.229154       0.000000                          0.407505                  41           0.003166
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P1            1.5        11960               0  0.301087 -19886.404783 -139486.404783    -11.662743       0.918808    -177708.633623    -95.000000 -350.000000      345.0                   0.286873                0.713127                     0.119900       0.000000                          0.593227                  22           0.001839
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P3            0.5        16879               0  0.189822 -78374.567120 -247164.567120    -14.643318       0.813211    -252262.208137    -62.133759 -165.117996      140.0                   0.508620                0.491380                     0.226139       0.184075                          0.081166                 174           0.010309
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P3            1.0        16057               0  0.281622 -60837.488213 -221407.488213    -13.788845       0.877577    -270127.331230    -80.000000 -271.444207      255.0                   0.362708                0.637292                     0.112848       0.381204                          0.143240                 241           0.015009
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P3            1.5        15539               0  0.325375 -65233.578040 -220623.578040    -14.198055       0.891639    -263646.498459    -75.000000 -333.526847      310.0                   0.283545                0.716455                     0.028123       0.506468                          0.181865                  94           0.006049
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P1            0.5         6009               0  0.157098 -52798.453198 -112888.453198    -18.786562       0.809100    -120482.167235    -85.000000 -195.000000      185.0                   0.503578                0.496422                     0.300050       0.000000                          0.196372                  11           0.001831
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P1            1.0         5130               0  0.254386 -41429.878010  -92729.878010    -18.076000       0.879148    -116214.309516   -120.000000 -332.861814      380.5                   0.361793                0.638207                     0.234698       0.000000                          0.403509                  19           0.003704
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P1            1.5         4703               0  0.309164 -26489.017977  -73519.017977    -15.632366       0.911210     -86190.551503   -125.000000 -442.625701      490.0                   0.279183                0.720817                     0.125452       0.000000                          0.595365                   8           0.001701
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P3            0.5         6789               0  0.189719 -27626.930305  -95516.930305    -14.069367       0.849750     -98995.240448    -80.995999 -191.312552      190.0                   0.509943                0.490057                     0.234644       0.180586                          0.074827                  77           0.011342
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P3            1.0         6447               0  0.287731 -41485.617196 -105955.617196    -16.434872       0.880868    -120310.218125   -105.323775 -326.009671      350.0                   0.364200                0.635800                     0.114937       0.389018                          0.131844                  94           0.014580
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P3            1.5         6235               0  0.334082 -22157.417472  -84507.417472    -13.553716       0.914012     -97249.511010    -95.000000 -413.531550      430.0                   0.275060                0.724940                     0.028228       0.530553                          0.166159                  30           0.004812

11. Policy comparison

                       execution_contract  year policy  stop_atr_mult  trade_count  censored_count  win_rate      gross_pnl        net_pnl  ev_per_trade  profit_factor  maximum_drawdown  median_trade   p10_trade  p90_trade  stop_out_before_flip_rate  flip_confirmation_rate  post_confirmation_stop_rate  d10_exit_rate  opposite_flip_fallback_exit_rate  same_bar_tie_count  same_bar_tie_rate
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P0            NaN        18323               0  0.323255   38455.000000 -144775.000000     -7.901272       0.953007    -238060.000000    -90.000000 -430.000000      440.0                   0.000000                1.000000                     0.000000       0.000000                          1.000000                   0           0.000000
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P1            0.5        15019               0  0.157734  -90646.463215 -240836.463215    -16.035453       0.803625    -263686.941597    -65.000000 -166.961601      125.0                   0.505693                0.494307                     0.296291       0.000000                          0.198016                  32           0.002131
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P1            1.0        12952               0  0.245290  -65129.756405 -194649.756405    -15.028548       0.876514    -251618.756726    -90.000000 -280.525433      274.5                   0.363342                0.636658                     0.229154       0.000000                          0.407505                  41           0.003166
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P1            1.5        11960               0  0.301087  -19886.404783 -139486.404783    -11.662743       0.918808    -177708.633623    -95.000000 -350.000000      345.0                   0.286873                0.713127                     0.119900       0.000000                          0.593227                  22           0.001839
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P2            NaN        21139               0  0.295804 -101540.000000 -312930.000000    -14.803444       0.876758    -352665.000000    -75.000000 -295.000000      290.0                   0.000000                1.000000                     0.000000       0.764464                          0.235536                   0           0.000000
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P3            0.5        16879               0  0.189822  -78374.567120 -247164.567120    -14.643318       0.813211    -252262.208137    -62.133759 -165.117996      140.0                   0.508620                0.491380                     0.226139       0.184075                          0.081166                 174           0.010309
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P3            1.0        16057               0  0.281622  -60837.488213 -221407.488213    -13.788845       0.877577    -270127.331230    -80.000000 -271.444207      255.0                   0.362708                0.637292                     0.112848       0.381204                          0.143240                 241           0.015009
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025     P3            1.5        15539               0  0.325375  -65233.578040 -220623.578040    -14.198055       0.891639    -263646.498459    -75.000000 -333.526847      310.0                   0.283545                0.716455                     0.028123       0.506468                          0.181865                  94           0.006049
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025    P4A            0.5         3033               0  0.142763  -54734.828472  -85064.828472    -28.046432       0.666216     -88963.821642    -62.776008 -165.073575       90.0                   0.641279                0.358721                     0.176393       0.000000                          0.182328                   2           0.000659
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025    P4A            1.0         2989               0  0.218133  -92997.413394 -122887.413394    -41.113220       0.681434    -125478.520039    -93.923083 -286.763518      225.0                   0.528270                0.471730                     0.118434       0.000000                          0.353295                   1           0.000335
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025    P4A            1.5         2968               0  0.271563 -120702.784174 -150382.784174    -50.668054       0.681083    -151979.714136   -107.565749 -370.504076      296.5                   0.436658                0.563342                     0.074461       0.000000                          0.488881                   6           0.002022
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025    P4B            0.5         3033               0  0.172437  -54835.047311  -85165.047311    -28.079475       0.643966     -89321.205990    -60.000000 -160.000000       99.0                   0.641279                0.358721                     0.108803       0.217936                          0.031982                  21           0.006924
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025    P4B            1.0         2989               0  0.249916  -89881.616876 -119771.616876    -40.070799       0.658918    -122962.470174    -82.794952 -262.779154      185.0                   0.528270                0.471730                     0.040147       0.375376                          0.056206                  25           0.008364
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2025    P4B            1.5         2968               0  0.297507 -125595.053334 -155275.053334    -52.316393       0.632802    -159284.524481    -90.000000 -345.042481      255.0                   0.436658                0.563342                     0.008760       0.486860                          0.067722                   6           0.002022
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P0            NaN         7353               1  0.323269 -182885.000000 -256415.000000    -34.872161       0.834897    -276690.000000   -120.000000 -534.000000      535.0                   0.000000                1.000000                     0.000000       0.000000                          1.000000                   0           0.000000
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P1            0.5         6009               0  0.157098  -52798.453198 -112888.453198    -18.786562       0.809100    -120482.167235    -85.000000 -195.000000      185.0                   0.503578                0.496422                     0.300050       0.000000                          0.196372                  11           0.001831
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P1            1.0         5130               0  0.254386  -41429.878010  -92729.878010    -18.076000       0.879148    -116214.309516   -120.000000 -332.861814      380.5                   0.361793                0.638207                     0.234698       0.000000                          0.403509                  19           0.003704
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P1            1.5         4703               0  0.309164  -26489.017977  -73519.017977    -15.632366       0.911210     -86190.551503   -125.000000 -442.625701      490.0                   0.279183                0.720817                     0.125452       0.000000                          0.595365                   8           0.001701
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P2            NaN         8401               1  0.297227 -101165.000000 -185175.000000    -22.042019       0.851757    -203895.000000   -100.000000 -365.000000      380.0                   0.000000                1.000000                     0.000000       0.784907                          0.215093                   0           0.000000
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P3            0.5         6789               0  0.189719  -27626.930305  -95516.930305    -14.069367       0.849750     -98995.240448    -80.995999 -191.312552      190.0                   0.509943                0.490057                     0.234644       0.180586                          0.074827                  77           0.011342
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P3            1.0         6447               0  0.287731  -41485.617196 -105955.617196    -16.434872       0.880868    -120310.218125   -105.323775 -326.009671      350.0                   0.364200                0.635800                     0.114937       0.389018                          0.131844                  94           0.014580
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026     P3            1.5         6235               0  0.334082  -22157.417472  -84507.417472    -13.553716       0.914012     -97249.511010    -95.000000 -413.531550      430.0                   0.275060                0.724940                     0.028228       0.530553                          0.166159                  30           0.004812
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026    P4A            0.5         1144               0  0.152972  -26893.307712  -38333.307712    -33.508136       0.654213     -42918.278744    -82.634803 -190.728150      120.0                   0.635490                0.364510                     0.167832       0.000000                          0.196678                   0           0.000000
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026    P4A            1.0         1132               0  0.235866  -55502.936315  -66822.936315    -59.030862       0.622476     -69653.212941   -125.767925 -345.686404      285.0                   0.508834                0.491166                     0.123675       0.000000                          0.367491                   4           0.003534
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026    P4A            1.5         1124               0  0.291815  -64194.021131  -75434.021131    -67.112118       0.647173     -79365.698044   -140.000000 -463.666876      388.5                   0.403915                0.596085                     0.064057       0.000000                          0.532028                   0           0.000000
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026    P4B            0.5         1144               0  0.180070  -24814.341845  -36254.341845    -31.690858       0.656078     -39711.729264    -79.769937 -187.831350      145.0                   0.635490                0.364510                     0.111014       0.225524                          0.027972                   8           0.006993
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026    P4B            1.0         1132               0  0.269435  -46881.356890  -58201.356890    -51.414626       0.626415     -60480.542606   -110.000000 -329.564952      274.5                   0.508834                0.491166                     0.035336       0.412544                          0.043286                   4           0.003534
EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT  2026    P4B            1.5         1124               0  0.325623  -61084.948561  -72324.948561    -64.346040       0.612126     -75555.210403   -100.724906 -442.505518      333.5                   0.403915                0.596085                     0.010676       0.527580                          0.057829                   1           0.000890

12. D10 exit versus opposite-flip fallback

See d10_exit_contribution.parquet and d10_exit_reason_summary.parquet.

13. Same-timestamp event analysis

Stop/logical-exit tie count: 1815.

14. Matched placebo controls

See matched_placebo_summary, pairs, and balance artifacts. Maximum absolute design SMD: 0.418; executed-pair SMD: 0.215.

15. Tail dependence and runner capture

See tail_dependence.parquet and runner_capture.parquet.

16. Failure modes

No tick/quote path; intrabar ordering unknown; Contract 2 stop price is an OHLC assumption; Contract 3 sensitivity only; zero-exit months count non-positive.

17. Decision recommendation

CLOSE. Research conclusion only, not executable validation or parameter selection.