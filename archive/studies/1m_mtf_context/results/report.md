# MTF Context Collector — Full Analysis Report


Generated from `studies/1m_mtf_context/analysis/*.py`



## Analysis 1-2: Bar+1 Close Features

```
====================================================================================================
ANALYSIS 1-2: Bar+1 Close Features
====================================================================================================

  113,966 trades loaded


--- Split 1: bar1_close_above_flip_close (1=bar+1 closed beyond flip close in flip direction) ---

  bar1_above_flip=1                    N=70,245  MFE= 2.58  PT= 48.4%  SL= 51.3%  Reg=  0.4%  Avg=$  -7.4  Tot=$  -517,429  PF= 0.86
  bar1_above_flip=0                    N=43,721  MFE= 2.25  PT= 49.2%  SL= 47.6%  Reg=  3.3%  Avg=$  -5.7  Tot=$  -247,672  PF= 0.89


--- Split 2: bar1_close_above_50pct_range (direction-aware) ---

  bar1_above_50pct_range=1             N=61,489  MFE= 2.58  PT= 48.2%  SL= 51.5%  Reg=  0.4%  Avg=$  -7.5  Tot=$  -462,964  PF= 0.86
  bar1_above_50pct_range=0             N=52,477  MFE= 2.31  PT= 49.2%  SL= 48.0%  Reg=  2.8%  Avg=$  -5.8  Tot=$  -302,137  PF= 0.89


--- Quintile: bar1_close_location (direction-aware) ---

  Q1 [0.00, 0.20]                      N=22,943  MFE= 2.26  PT= 49.3%  SL= 46.1%  Reg=  4.6%  Avg=$  -5.6  Tot=$  -128,396  PF= 0.89
  Q2 [0.20, 0.44]                      N=22,699  MFE= 2.32  PT= 49.4%  SL= 49.1%  Reg=  1.6%  Avg=$  -5.6  Tot=$  -126,019  PF= 0.90
  Q3 [0.45, 0.67]                      N=23,967  MFE= 2.47  PT= 49.1%  SL= 50.3%  Reg=  0.6%  Avg=$  -6.9  Tot=$  -164,988  PF= 0.87
  Q4 [0.67, 0.85]                      N=21,724  MFE= 2.58  PT= 48.5%  SL= 51.1%  Reg=  0.4%  Avg=$  -6.9  Tot=$  -150,285  PF= 0.88
  Q5 [0.85, 1.00]                      N=22,633  MFE= 2.66  PT= 47.0%  SL= 52.7%  Reg=  0.3%  Avg=$  -8.6  Tot=$  -195,414  PF= 0.84


--- Quintile: bar1_body_pct (body as % of range) ---

  Q1 [0.00, 0.19]                      N=22,849  MFE= 2.45  PT= 49.0%  SL= 50.2%  Reg=  0.9%  Avg=$  -6.3  Tot=$  -143,270  PF= 0.88
  Q2 [0.19, 0.36]                      N=22,778  MFE= 2.39  PT= 49.3%  SL= 49.7%  Reg=  1.0%  Avg=$  -6.2  Tot=$  -142,270  PF= 0.88
  Q3 [0.36, 0.52]                      N=22,790  MFE= 2.40  PT= 48.9%  SL= 49.7%  Reg=  1.4%  Avg=$  -7.2  Tot=$  -164,281  PF= 0.87
  Q4 [0.52, 0.70]                      N=23,011  MFE= 2.44  PT= 48.5%  SL= 49.4%  Reg=  2.1%  Avg=$  -6.5  Tot=$  -149,078  PF= 0.88
  Q5 [0.70, 1.00]                      N=22,538  MFE= 2.61  PT= 47.6%  SL= 50.3%  Reg=  2.1%  Avg=$  -7.4  Tot=$  -166,202  PF= 0.85


--- Quintile: bar1_hh_amount_atr (strength of confirmation) ---

  Q1 [0.004, 0.176]                    N=22,794  MFE= 2.12  PT= 48.6%  SL= 48.1%  Reg=  3.3%  Avg=$  -6.1  Tot=$  -138,371  PF= 0.90
  Q2 [0.176, 0.341]                    N=22,793  MFE= 2.25  PT= 49.3%  SL= 48.5%  Reg=  2.2%  Avg=$  -5.1  Tot=$  -115,397  PF= 0.90
  Q3 [0.341, 0.553]                    N=22,793  MFE= 2.33  PT= 48.3%  SL= 50.5%  Reg=  1.2%  Avg=$  -8.1  Tot=$  -185,658  PF= 0.85
  Q4 [0.553, 0.897]                    N=22,829  MFE= 2.52  PT= 48.4%  SL= 51.0%  Reg=  0.6%  Avg=$  -7.4  Tot=$  -169,161  PF= 0.86
  Q5 [0.898, 616.000]                  N=22,757  MFE= 3.07  PT= 48.7%  SL= 51.1%  Reg=  0.2%  Avg=$  -6.9  Tot=$  -156,514  PF= 0.85

====================================================================================================

```


## Analysis 3: Multi-Timeframe Alignment

```
====================================================================================================
ANALYSIS 3: Multi-Timeframe Regime Alignment
====================================================================================================

  113,966 trades loaded


--- Regime alignment score (1m/5m/15m) ---

  alignment_score=1                    N=41,556  MFE= 2.30  PT= 48.7%  SL= 49.5%  Reg=  1.8%  Avg=$  -7.2  Tot=$  -298,541  PF= 0.87
  alignment_score=2                    N=32,720  MFE= 2.46  PT= 49.0%  SL= 49.6%  Reg=  1.4%  Avg=$  -5.6  Tot=$  -182,346  PF= 0.89
  alignment_score=3                    N=39,690  MFE= 2.61  PT= 48.4%  SL= 50.4%  Reg=  1.2%  Avg=$  -7.2  Tot=$  -284,215  PF= 0.87


--- 5m alignment only ---

  regime_5m_aligned=1                  N=55,491  MFE= 2.58  PT= 48.5%  SL= 50.4%  Reg=  1.2%  Avg=$  -6.7  Tot=$  -370,490  PF= 0.87
  regime_5m_aligned=0                  N=58,475  MFE= 2.33  PT= 48.9%  SL= 49.4%  Reg=  1.8%  Avg=$  -6.7  Tot=$  -394,611  PF= 0.87


--- 15m alignment only ---

  regime_15m_aligned=1                 N=56,609  MFE= 2.55  PT= 48.7%  SL= 50.0%  Reg=  1.3%  Avg=$  -6.7  Tot=$  -380,286  PF= 0.87
  regime_15m_aligned=0                 N=57,357  MFE= 2.36  PT= 48.6%  SL= 49.7%  Reg=  1.7%  Avg=$  -6.7  Tot=$  -384,815  PF= 0.87


--- all_regimes_aligned (1m+5m+15m same direction) ---

  all_regimes_aligned=1                N=39,690  MFE= 2.61  PT= 48.4%  SL= 50.4%  Reg=  1.2%  Avg=$  -7.2  Tot=$  -284,215  PF= 0.87
  all_regimes_aligned=0                N=74,276  MFE= 2.37  PT= 48.8%  SL= 49.5%  Reg=  1.7%  Avg=$  -6.5  Tot=$  -480,886  PF= 0.88


--- 5m regime duration (quintiles) ---

  Q1 5m dur [1, 4]                     N=26,516  MFE= 2.38  PT= 48.7%  SL= 49.6%  Reg=  1.7%  Avg=$  -7.6  Tot=$  -202,390  PF= 0.86
  Q2 5m dur [5, 7]                     N=19,648  MFE= 2.42  PT= 48.6%  SL= 49.9%  Reg=  1.5%  Avg=$  -5.7  Tot=$  -112,467  PF= 0.89
  Q3 5m dur [8, 12]                    N=23,791  MFE= 2.47  PT= 48.6%  SL= 50.0%  Reg=  1.3%  Avg=$  -6.7  Tot=$  -159,192  PF= 0.87
  Q4 5m dur [13, 20]                   N=21,655  MFE= 2.47  PT= 48.8%  SL= 49.9%  Reg=  1.3%  Avg=$  -6.5  Tot=$  -140,450  PF= 0.88
  Q5 5m dur [21, 118]                  N=22,356  MFE= 2.55  PT= 48.6%  SL= 49.8%  Reg=  1.6%  Avg=$  -6.7  Tot=$  -150,602  PF= 0.87


--- 15m regime duration (quintiles) ---

  Q1 15m dur [1, 4]                    N=29,457  MFE= 2.39  PT= 48.5%  SL= 50.0%  Reg=  1.5%  Avg=$  -6.7  Tot=$  -198,670  PF= 0.89
  Q2 15m dur [5, 7]                    N=17,876  MFE= 2.38  PT= 48.7%  SL= 49.8%  Reg=  1.5%  Avg=$  -7.4  Tot=$  -132,898  PF= 0.87
  Q3 15m dur [8, 12]                   N=21,859  MFE= 2.43  PT= 49.1%  SL= 49.4%  Reg=  1.5%  Avg=$  -6.1  Tot=$  -134,076  PF= 0.88
  Q4 15m dur [13, 21]                  N=22,387  MFE= 2.58  PT= 48.8%  SL= 49.8%  Reg=  1.4%  Avg=$  -6.3  Tot=$  -139,933  PF= 0.88
  Q5 15m dur [22, 120]                 N=22,387  MFE= 2.51  PT= 48.3%  SL= 50.2%  Reg=  1.5%  Avg=$  -7.1  Tot=$  -159,525  PF= 0.85

====================================================================================================

```


## Analysis 4: Volume at Flip + Bar+1

```
====================================================================================================
ANALYSIS 4: Volume at flip + bar+1
====================================================================================================

  113,966 trades loaded


--- Quintile: flip_vol_vs_20avg ---

  Q1 [0.03, 0.67]                      N=22,795  MFE= 2.27  PT= 48.0%  SL= 49.0%  Reg=  3.0%  Avg=$  -7.1  Tot=$  -161,142  PF= 0.83
  Q2 [0.67, 0.88]                      N=22,792  MFE= 2.33  PT= 48.6%  SL= 49.7%  Reg=  1.7%  Avg=$  -7.1  Tot=$  -160,876  PF= 0.87
  Q3 [0.88, 1.10]                      N=22,793  MFE= 2.38  PT= 48.5%  SL= 50.3%  Reg=  1.2%  Avg=$  -7.0  Tot=$  -158,876  PF= 0.88
  Q4 [1.10, 1.45]                      N=22,793  MFE= 2.46  PT= 49.4%  SL= 49.8%  Reg=  0.9%  Avg=$  -6.3  Tot=$  -143,100  PF= 0.89
  Q5 [1.45, 12.32]                     N=22,793  MFE= 2.84  PT= 48.8%  SL= 50.5%  Reg=  0.6%  Avg=$  -6.2  Tot=$  -141,107  PF= 0.88


--- Quintile: bar1_vol_vs_20avg ---

  Q1 [0.03, 0.70]                      N=22,794  MFE= 2.13  PT= 48.3%  SL= 48.6%  Reg=  3.1%  Avg=$  -6.7  Tot=$  -153,562  PF= 0.86
  Q2 [0.70, 0.94]                      N=22,793  MFE= 2.22  PT= 48.7%  SL= 49.5%  Reg=  1.8%  Avg=$  -6.5  Tot=$  -148,048  PF= 0.89
  Q3 [0.94, 1.21]                      N=22,793  MFE= 2.37  PT= 49.1%  SL= 49.6%  Reg=  1.3%  Avg=$  -6.2  Tot=$  -142,261  PF= 0.89
  Q4 [1.21, 1.70]                      N=22,793  MFE= 2.52  PT= 48.5%  SL= 50.7%  Reg=  0.9%  Avg=$  -6.7  Tot=$  -151,719  PF= 0.88
  Q5 [1.70, 46.83]                     N=22,793  MFE= 3.05  PT= 48.7%  SL= 50.9%  Reg=  0.4%  Avg=$  -7.4  Tot=$  -169,511  PF= 0.84


--- Quintile: bar1_vol_vs_flip_vol ---

  Q1 [0.04, 0.70]                      N=22,800  MFE= 2.37  PT= 48.9%  SL= 49.3%  Reg=  1.7%  Avg=$  -5.9  Tot=$  -134,553  PF= 0.88
  Q2 [0.70, 0.93]                      N=22,787  MFE= 2.39  PT= 49.0%  SL= 49.6%  Reg=  1.5%  Avg=$  -6.3  Tot=$  -143,998  PF= 0.90
  Q3 [0.93, 1.21]                      N=22,794  MFE= 2.36  PT= 48.7%  SL= 49.9%  Reg=  1.5%  Avg=$  -6.7  Tot=$  -152,918  PF= 0.89
  Q4 [1.21, 1.70]                      N=22,792  MFE= 2.48  PT= 48.7%  SL= 49.8%  Reg=  1.5%  Avg=$  -6.7  Tot=$  -152,773  PF= 0.88
  Q5 [1.70, 70.20]                     N=22,793  MFE= 2.68  PT= 48.0%  SL= 50.8%  Reg=  1.2%  Avg=$  -7.9  Tot=$  -180,859  PF= 0.81


--- Quintile: flip_bar_bullish_volume_pct ---

  Q1 [0.000, 0.289]                    N=22,796  MFE= 2.56  PT= 48.5%  SL= 49.9%  Reg=  1.6%  Avg=$  -5.8  Tot=$  -132,370  PF= 0.85
  Q2 [0.290, 0.423]                    N=22,791  MFE= 2.49  PT= 48.4%  SL= 50.4%  Reg=  1.3%  Avg=$  -7.3  Tot=$  -166,519  PF= 0.89
  Q3 [0.423, 0.569]                    N=22,797  MFE= 2.40  PT= 48.6%  SL= 49.7%  Reg=  1.7%  Avg=$  -7.1  Tot=$  -161,176  PF= 0.88
  Q4 [0.569, 0.703]                    N=22,798  MFE= 2.39  PT= 49.0%  SL= 49.7%  Reg=  1.3%  Avg=$  -7.7  Tot=$  -176,062  PF= 0.88
  Q5 [0.703, 1.000]                    N=22,784  MFE= 2.43  PT= 48.8%  SL= 49.6%  Reg=  1.6%  Avg=$  -5.7  Tot=$  -128,974  PF= 0.85


--- Quintile: bar1_bullish_volume_pct ---

  Q1 [0.000, 0.343]                    N=22,796  MFE= 2.56  PT= 47.7%  SL= 50.6%  Reg=  1.6%  Avg=$  -7.4  Tot=$  -168,956  PF= 0.81
  Q2 [0.343, 0.452]                    N=22,791  MFE= 2.46  PT= 48.8%  SL= 49.9%  Reg=  1.3%  Avg=$  -6.6  Tot=$  -150,375  PF= 0.89
  Q3 [0.452, 0.541]                    N=22,801  MFE= 2.39  PT= 48.8%  SL= 49.9%  Reg=  1.3%  Avg=$  -7.4  Tot=$  -167,712  PF= 0.89
  Q4 [0.541, 0.653]                    N=22,785  MFE= 2.32  PT= 48.8%  SL= 49.7%  Reg=  1.5%  Avg=$  -6.8  Tot=$  -154,471  PF= 0.89
  Q5 [0.653, 1.000]                    N=22,793  MFE= 2.54  PT= 49.1%  SL= 49.2%  Reg=  1.7%  Avg=$  -5.4  Tot=$  -123,586  PF= 0.86


--- Quintile: cumulative_volume_bias_10 ---

  Q1 [-1.000, -0.236]                  N=22,794  MFE= 2.48  PT= 48.9%  SL= 49.5%  Reg=  1.6%  Avg=$  -5.4  Tot=$  -123,209  PF= 0.89
  Q2 [-0.236, -0.073]                  N=22,793  MFE= 2.45  PT= 48.7%  SL= 49.9%  Reg=  1.4%  Avg=$  -7.7  Tot=$  -174,581  PF= 0.86
  Q3 [-0.073, 0.066]                   N=22,793  MFE= 2.41  PT= 48.6%  SL= 50.0%  Reg=  1.4%  Avg=$  -6.3  Tot=$  -142,796  PF= 0.89
  Q4 [0.066, 0.229]                    N=22,793  MFE= 2.39  PT= 48.5%  SL= 50.1%  Reg=  1.4%  Avg=$  -7.3  Tot=$  -166,069  PF= 0.87
  Q5 [0.229, 1.000]                    N=22,793  MFE= 2.54  PT= 48.5%  SL= 49.8%  Reg=  1.6%  Avg=$  -7.0  Tot=$  -158,446  PF= 0.86


--- Quintile: vol_acceleration_5bar ---

  Q1 [0.05, 0.67]                      N=22,794  MFE= 2.20  PT= 48.0%  SL= 49.2%  Reg=  2.8%  Avg=$  -8.0  Tot=$  -181,999  PF= 0.83
  Q2 [0.67, 0.84]                      N=22,793  MFE= 2.35  PT= 48.4%  SL= 50.1%  Reg=  1.5%  Avg=$  -8.1  Tot=$  -183,871  PF= 0.86
  Q3 [0.84, 1.03]                      N=22,793  MFE= 2.43  PT= 48.5%  SL= 50.2%  Reg=  1.3%  Avg=$  -6.6  Tot=$  -150,052  PF= 0.89
  Q4 [1.03, 1.32]                      N=22,793  MFE= 2.48  PT= 48.9%  SL= 50.0%  Reg=  1.1%  Avg=$  -5.6  Tot=$  -127,392  PF= 0.90
  Q5 [1.32, 390.85]                    N=22,793  MFE= 2.82  PT= 49.5%  SL= 49.7%  Reg=  0.8%  Avg=$  -5.3  Tot=$  -121,787  PF= 0.88


--- Quintile: flip_bar_vol_rank_20 ---

  Q1 [0.000, 0.250]                    N=24,361  MFE= 2.27  PT= 48.3%  SL= 49.1%  Reg=  2.6%  Avg=$  -7.3  Tot=$  -178,996  PF= 0.86
  Q2 [0.300, 0.450]                    N=21,312  MFE= 2.33  PT= 48.3%  SL= 49.8%  Reg=  1.9%  Avg=$  -6.5  Tot=$  -139,114  PF= 0.88
  Q3 [0.500, 0.650]                    N=24,692  MFE= 2.38  PT= 48.5%  SL= 50.2%  Reg=  1.3%  Avg=$  -7.5  Tot=$  -184,758  PF= 0.86
  Q4 [0.700, 0.850]                    N=27,620  MFE= 2.49  PT= 49.3%  SL= 49.9%  Reg=  0.9%  Avg=$  -6.1  Tot=$  -169,048  PF= 0.88
  Q5 [0.900, 0.950]                    N=15,981  MFE= 2.97  PT= 48.9%  SL= 50.6%  Reg=  0.6%  Avg=$  -5.8  Tot=$   -93,186  PF= 0.89

====================================================================================================

```


## Analysis 5: Pre-Flip Compression

```
====================================================================================================
ANALYSIS 5: Pre-Flip Compression
====================================================================================================

  113,966 trades loaded


--- Quintile: pre_flip_3bar_range_atr ---

  Q1 [0.00, 1.15]                      N=22,794  MFE= 2.49  PT= 48.4%  SL= 49.4%  Reg=  2.2%  Avg=$  -7.6  Tot=$  -173,992  PF= 0.85
  Q2 [1.15, 1.37]                      N=22,804  MFE= 2.46  PT= 48.6%  SL= 49.9%  Reg=  1.5%  Avg=$  -7.1  Tot=$  -161,944  PF= 0.87
  Q3 [1.37, 1.60]                      N=22,791  MFE= 2.44  PT= 48.7%  SL= 49.9%  Reg=  1.4%  Avg=$  -6.9  Tot=$  -156,736  PF= 0.87
  Q4 [1.60, 1.91]                      N=22,791  MFE= 2.41  PT= 48.9%  SL= 49.9%  Reg=  1.2%  Avg=$  -5.4  Tot=$  -123,415  PF= 0.90
  Q5 [1.91, 8.50]                      N=22,786  MFE= 2.48  PT= 48.7%  SL= 50.3%  Reg=  1.0%  Avg=$  -6.5  Tot=$  -149,014  PF= 0.87


--- Quintile: pre_flip_5bar_range_atr ---

  Q1 [0.00, 1.52]                      N=22,798  MFE= 2.50  PT= 48.0%  SL= 49.9%  Reg=  2.1%  Avg=$  -8.0  Tot=$  -183,174  PF= 0.85
  Q2 [1.52, 1.78]                      N=22,792  MFE= 2.42  PT= 48.2%  SL= 50.4%  Reg=  1.4%  Avg=$  -8.2  Tot=$  -186,712  PF= 0.85
  Q3 [1.78, 2.04]                      N=22,799  MFE= 2.48  PT= 48.6%  SL= 49.9%  Reg=  1.4%  Avg=$  -7.5  Tot=$  -170,337  PF= 0.86
  Q4 [2.04, 2.39]                      N=22,784  MFE= 2.41  PT= 49.1%  SL= 49.5%  Reg=  1.4%  Avg=$  -5.2  Tot=$  -117,732  PF= 0.90
  Q5 [2.39, 8.52]                      N=22,793  MFE= 2.47  PT= 49.3%  SL= 49.6%  Reg=  1.1%  Avg=$  -4.7  Tot=$  -107,147  PF= 0.90


--- Quintile: pre_flip_3bar_body_direction ---

  Q1 [-3.72, -0.36]                    N=22,794  MFE= 2.52  PT= 48.8%  SL= 49.9%  Reg=  1.3%  Avg=$  -7.1  Tot=$  -160,833  PF= 0.86
  Q2 [-0.36, 0.08]                     N=22,802  MFE= 2.52  PT= 48.7%  SL= 49.8%  Reg=  1.5%  Avg=$  -6.6  Tot=$  -150,750  PF= 0.87
  Q3 [0.08, 0.43]                      N=22,792  MFE= 2.44  PT= 48.8%  SL= 49.6%  Reg=  1.6%  Avg=$  -6.7  Tot=$  -151,975  PF= 0.87
  Q4 [0.43, 0.82]                      N=22,806  MFE= 2.44  PT= 48.6%  SL= 49.9%  Reg=  1.5%  Avg=$  -7.0  Tot=$  -159,319  PF= 0.87
  Q5 [0.82, 4.45]                      N=22,772  MFE= 2.37  PT= 48.4%  SL= 50.1%  Reg=  1.4%  Avg=$  -6.2  Tot=$  -142,224  PF= 0.89


--- Quintile: consecutive_trend_bars_pre_flip ---

  Q1 [0, 1]                            N=76,433  MFE= 2.49  PT= 48.6%  SL= 50.0%  Reg=  1.5%  Avg=$  -7.2  Tot=$  -548,653  PF= 0.86
  Q2 [2, 2]                            N=24,388  MFE= 2.41  PT= 49.0%  SL= 49.6%  Reg=  1.4%  Avg=$  -6.1  Tot=$  -147,931  PF= 0.89
  Q3 [3, 9]                            N=13,145  MFE= 2.35  PT= 48.7%  SL= 49.6%  Reg=  1.7%  Avg=$  -5.2  Tot=$   -68,517  PF= 0.91


--- Quintile: pre_flip_volume_trend ---

  Q1 [0.02, 0.62]                      N=22,794  MFE= 2.33  PT= 48.5%  SL= 49.5%  Reg=  2.0%  Avg=$  -7.2  Tot=$  -164,056  PF= 0.84
  Q2 [0.62, 0.80]                      N=22,840  MFE= 2.38  PT= 49.0%  SL= 49.3%  Reg=  1.7%  Avg=$  -6.3  Tot=$  -144,716  PF= 0.89
  Q3 [0.80, 0.99]                      N=22,746  MFE= 2.41  PT= 48.1%  SL= 50.5%  Reg=  1.4%  Avg=$  -7.9  Tot=$  -178,688  PF= 0.87
  Q4 [0.99, 1.29]                      N=22,795  MFE= 2.45  PT= 48.6%  SL= 50.2%  Reg=  1.2%  Avg=$  -6.7  Tot=$  -151,814  PF= 0.88
  Q5 [1.29, 1548.75]                   N=22,791  MFE= 2.71  PT= 49.2%  SL= 49.7%  Reg=  1.1%  Avg=$  -5.5  Tot=$  -125,828  PF= 0.88


--- Quintile: prior_regime_duration_bars ---



--- Quintile: prior_regime_mfe_atr ---

  Q1 [0.00, 0.38]                      N=22,799  MFE= 2.51  PT= 49.1%  SL= 49.3%  Reg=  1.6%  Avg=$  -4.6  Tot=$  -105,924  PF= 0.91
  Q2 [0.38, 1.02]                      N=22,804  MFE= 2.48  PT= 48.8%  SL= 49.8%  Reg=  1.3%  Avg=$  -6.2  Tot=$  -142,457  PF= 0.88
  Q3 [1.02, 2.00]                      N=22,938  MFE= 2.50  PT= 48.4%  SL= 50.3%  Reg=  1.3%  Avg=$  -7.1  Tot=$  -162,634  PF= 0.87
  Q4 [2.00, 3.73]                      N=22,633  MFE= 2.42  PT= 48.7%  SL= 49.9%  Reg=  1.4%  Avg=$  -7.5  Tot=$  -168,793  PF= 0.86
  Q5 [3.73, 335000000000.00]           N=22,792  MFE= 2.38  PT= 48.3%  SL= 49.9%  Reg=  1.8%  Avg=$  -8.1  Tot=$  -185,293  PF= 0.86


--- Quintile: regime_flips_last_30min ---

  Q1 [1, 2]                            N=39,385  MFE= 2.45  PT= 48.2%  SL= 50.3%  Reg=  1.5%  Avg=$  -8.0  Tot=$  -316,123  PF= 0.85
  Q2 [3, 3]                            N=34,870  MFE= 2.45  PT= 49.1%  SL= 49.5%  Reg=  1.4%  Avg=$  -5.6  Tot=$  -193,722  PF= 0.89
  Q3 [4, 4]                            N=24,263  MFE= 2.48  PT= 49.1%  SL= 49.4%  Reg=  1.6%  Avg=$  -5.6  Tot=$  -136,411  PF= 0.89
  Q4 [5, 10]                           N=15,448  MFE= 2.45  PT= 48.3%  SL= 50.3%  Reg=  1.4%  Avg=$  -7.7  Tot=$  -118,845  PF= 0.85


--- Quintile: atr_14 ---

  Q1 [0.02, 2.68]                      N=23,034  MFE= 2.80  PT= 48.4%  SL= 50.2%  Reg=  1.4%  Avg=$  -5.9  Tot=$  -136,323  PF= 0.66
  Q2 [2.70, 4.05]                      N=22,632  MFE= 2.55  PT= 48.7%  SL= 49.9%  Reg=  1.4%  Avg=$  -6.1  Tot=$  -139,067  PF= 0.78
  Q3 [4.07, 5.98]                      N=22,804  MFE= 2.51  PT= 48.6%  SL= 49.9%  Reg=  1.4%  Avg=$  -6.7  Tot=$  -151,862  PF= 0.84
  Q4 [6.00, 9.52]                      N=22,760  MFE= 2.31  PT= 48.6%  SL= 49.8%  Reg=  1.5%  Avg=$  -7.5  Tot=$  -170,194  PF= 0.88
  Q5 [9.54, 195.36]                    N=22,736  MFE= 2.11  PT= 49.0%  SL= 49.3%  Reg=  1.7%  Avg=$  -7.4  Tot=$  -167,656  PF= 0.94

====================================================================================================

```


## Analysis 6: 5s Micro-Context

```
====================================================================================================
ANALYSIS 6: 5s Micro-Context
====================================================================================================

  113,966 trades loaded


--- Quintile: micro_trend_12bar_5s ---

  Q1 [-10.839, -1.140]                 N=22,801  MFE= 2.67  PT= 48.5%  SL= 50.5%  Reg=  1.0%  Avg=$  -6.5  Tot=$  -148,532  PF= 0.86
  Q2 [-1.139, -0.551]                  N=22,787  MFE= 2.43  PT= 48.1%  SL= 50.4%  Reg=  1.6%  Avg=$  -7.2  Tot=$  -163,704  PF= 0.88
  Q3 [-0.551, 0.538]                   N=22,801  MFE= 2.35  PT= 48.7%  SL= 49.0%  Reg=  2.3%  Avg=$  -6.3  Tot=$  -144,669  PF= 0.88
  Q4 [0.538, 1.105]                    N=22,800  MFE= 2.27  PT= 48.8%  SL= 49.7%  Reg=  1.5%  Avg=$  -7.7  Tot=$  -174,421  PF= 0.87
  Q5 [1.106, 14.000]                   N=22,777  MFE= 2.56  PT= 49.2%  SL= 49.8%  Reg=  1.0%  Avg=$  -5.9  Tot=$  -133,775  PF= 0.87


--- Quintile: micro_vol_acceleration_5s ---

  Q1 [0.037, 0.667]                    N=22,794  MFE= 2.47  PT= 49.3%  SL= 49.0%  Reg=  1.7%  Avg=$  -5.6  Tot=$  -126,643  PF= 0.89
  Q2 [0.667, 0.911]                    N=22,812  MFE= 2.40  PT= 48.4%  SL= 50.2%  Reg=  1.4%  Avg=$  -7.6  Tot=$  -172,634  PF= 0.87
  Q3 [0.911, 1.192]                    N=22,774  MFE= 2.38  PT= 48.5%  SL= 49.9%  Reg=  1.5%  Avg=$  -6.7  Tot=$  -153,326  PF= 0.88
  Q4 [1.192, 1.642]                    N=22,793  MFE= 2.46  PT= 48.8%  SL= 49.7%  Reg=  1.5%  Avg=$  -6.1  Tot=$  -139,748  PF= 0.89
  Q5 [1.642, 35.388]                   N=22,793  MFE= 2.58  PT= 48.3%  SL= 50.4%  Reg=  1.3%  Avg=$  -7.6  Tot=$  -172,751  PF= 0.85


--- Quintile: micro_range_compression_5s ---

  Q1 [0.000, 0.727]                    N=22,913  MFE= 2.44  PT= 49.0%  SL= 49.3%  Reg=  1.7%  Avg=$  -6.1  Tot=$  -140,062  PF= 0.88
  Q2 [0.727, 0.900]                    N=22,722  MFE= 2.37  PT= 48.7%  SL= 49.9%  Reg=  1.4%  Avg=$  -6.7  Tot=$  -152,061  PF= 0.89
  Q3 [0.900, 1.089]                    N=22,746  MFE= 2.48  PT= 48.7%  SL= 49.9%  Reg=  1.4%  Avg=$  -6.7  Tot=$  -152,992  PF= 0.88
  Q4 [1.089, 1.381]                    N=22,816  MFE= 2.44  PT= 48.7%  SL= 49.8%  Reg=  1.5%  Avg=$  -6.9  Tot=$  -157,727  PF= 0.87
  Q5 [1.382, 28.303]                   N=22,769  MFE= 2.55  PT= 48.2%  SL= 50.4%  Reg=  1.4%  Avg=$  -7.1  Tot=$  -162,258  PF= 0.83


--- Quintile: micro_body_pct_avg_5s ---

  Q1 [0.017, 0.469]                    N=22,794  MFE= 2.54  PT= 48.5%  SL= 50.0%  Reg=  1.5%  Avg=$  -7.3  Tot=$  -166,674  PF= 0.89
  Q2 [0.469, 0.528]                    N=22,829  MFE= 2.42  PT= 48.6%  SL= 50.1%  Reg=  1.3%  Avg=$  -6.6  Tot=$  -150,033  PF= 0.89
  Q3 [0.528, 0.581]                    N=22,772  MFE= 2.44  PT= 49.1%  SL= 49.4%  Reg=  1.5%  Avg=$  -5.9  Tot=$  -135,215  PF= 0.89
  Q4 [0.581, 0.644]                    N=22,778  MFE= 2.43  PT= 48.9%  SL= 49.7%  Reg=  1.4%  Avg=$  -6.7  Tot=$  -151,964  PF= 0.86
  Q5 [0.644, 0.958]                    N=22,793  MFE= 2.45  PT= 48.2%  SL= 50.1%  Reg=  1.7%  Avg=$  -7.1  Tot=$  -161,214  PF= 0.82


--- Quintile: micro_hh_count_12_5s ---

  Q1 [0, 3]                            N=33,565  MFE= 2.56  PT= 48.4%  SL= 50.2%  Reg=  1.5%  Avg=$  -6.9  Tot=$  -230,100  PF= 0.88
  Q2 [4, 4]                            N=18,258  MFE= 2.52  PT= 48.1%  SL= 50.3%  Reg=  1.6%  Avg=$  -6.6  Tot=$  -121,158  PF= 0.86
  Q3 [5, 5]                            N=18,255  MFE= 2.47  PT= 49.0%  SL= 49.5%  Reg=  1.5%  Avg=$  -6.6  Tot=$  -119,747  PF= 0.85
  Q4 [6, 7]                            N=32,153  MFE= 2.38  PT= 49.0%  SL= 49.5%  Reg=  1.5%  Avg=$  -6.5  Tot=$  -210,560  PF= 0.88
  Q5 [8, 11]                           N=11,735  MFE= 2.26  PT= 48.9%  SL= 49.8%  Reg=  1.3%  Avg=$  -7.1  Tot=$   -83,537  PF= 0.90


--- Quintile: micro_hl_count_12_5s ---

  Q1 [0, 3]                            N=28,802  MFE= 2.60  PT= 48.9%  SL= 49.7%  Reg=  1.4%  Avg=$  -6.0  Tot=$  -172,431  PF= 0.88
  Q2 [4, 4]                            N=19,342  MFE= 2.54  PT= 48.1%  SL= 50.4%  Reg=  1.5%  Avg=$  -6.9  Tot=$  -132,622  PF= 0.86
  Q3 [5, 6]                            N=34,835  MFE= 2.45  PT= 48.6%  SL= 49.7%  Reg=  1.6%  Avg=$  -7.0  Tot=$  -244,220  PF= 0.85
  Q4 [7, 7]                            N=14,764  MFE= 2.31  PT= 48.7%  SL= 49.7%  Reg=  1.6%  Avg=$  -7.4  Tot=$  -109,948  PF= 0.87
  Q5 [8, 11]                           N=16,223  MFE= 2.24  PT= 49.0%  SL= 49.9%  Reg=  1.1%  Avg=$  -6.5  Tot=$  -105,880  PF= 0.91


--- Quintile: micro_up_vol_pct_12_5s ---

  Q1 [0.000, 0.266]                    N=22,805  MFE= 2.53  PT= 48.9%  SL= 49.8%  Reg=  1.3%  Avg=$  -6.1  Tot=$  -138,287  PF= 0.89
  Q2 [0.266, 0.415]                    N=22,782  MFE= 2.46  PT= 48.1%  SL= 50.3%  Reg=  1.6%  Avg=$  -7.9  Tot=$  -178,844  PF= 0.85
  Q3 [0.415, 0.584]                    N=22,793  MFE= 2.49  PT= 48.5%  SL= 49.7%  Reg=  1.7%  Avg=$  -6.6  Tot=$  -151,169  PF= 0.85
  Q4 [0.584, 0.732]                    N=22,803  MFE= 2.36  PT= 48.7%  SL= 49.8%  Reg=  1.5%  Avg=$  -6.1  Tot=$  -138,480  PF= 0.89
  Q5 [0.732, 1.000]                    N=22,783  MFE= 2.43  PT= 49.1%  SL= 49.6%  Reg=  1.3%  Avg=$  -6.9  Tot=$  -158,321  PF= 0.88


--- Quintile: micro_max_retracement_5s ---

  Q1 [0.000, 0.304]                    N=22,804  MFE= 2.25  PT= 48.8%  SL= 49.5%  Reg=  1.6%  Avg=$  -7.3  Tot=$  -166,320  PF= 0.90
  Q2 [0.305, 0.631]                    N=22,785  MFE= 2.35  PT= 49.1%  SL= 49.3%  Reg=  1.6%  Avg=$  -5.6  Tot=$  -126,915  PF= 0.90
  Q3 [0.631, 1.056]                    N=22,791  MFE= 2.44  PT= 48.8%  SL= 49.4%  Reg=  1.8%  Avg=$  -6.3  Tot=$  -144,667  PF= 0.88
  Q4 [1.057, 1.538]                    N=22,800  MFE= 2.51  PT= 48.3%  SL= 50.3%  Reg=  1.4%  Avg=$  -8.3  Tot=$  -188,298  PF= 0.83
  Q5 [1.538, 32.356]                   N=22,786  MFE= 2.73  PT= 48.2%  SL= 50.8%  Reg=  1.0%  Avg=$  -6.1  Tot=$  -138,901  PF= 0.83


--- Quintile: bar1_internals_up_pct ---

  Q1 [0.000, 0.286]                    N=24,179  MFE= 2.56  PT= 48.4%  SL= 49.8%  Reg=  1.8%  Avg=$  -6.9  Tot=$  -167,022  PF= 0.82
  Q2 [0.300, 0.400]                    N=21,830  MFE= 2.54  PT= 48.5%  SL= 50.2%  Reg=  1.2%  Avg=$  -7.3  Tot=$  -158,467  PF= 0.86
  Q3 [0.417, 0.500]                    N=33,548  MFE= 2.37  PT= 48.8%  SL= 49.8%  Reg=  1.4%  Avg=$  -6.5  Tot=$  -217,059  PF= 0.89
  Q4 [0.545, 0.600]                    N=13,267  MFE= 2.37  PT= 48.5%  SL= 50.3%  Reg=  1.2%  Avg=$  -7.4  Tot=$   -98,517  PF= 0.89
  Q5 [0.625, 1.000]                    N=21,142  MFE= 2.43  PT= 49.0%  SL= 49.3%  Reg=  1.7%  Avg=$  -5.9  Tot=$  -124,036  PF= 0.88


--- Quintile: bar1_internals_trend_5s ---

  Q1 [-16.540, -0.475]                 N=22,807  MFE= 2.74  PT= 48.0%  SL= 50.4%  Reg=  1.5%  Avg=$  -7.7  Tot=$  -174,768  PF= 0.86
  Q2 [-0.475, -0.110]                  N=22,818  MFE= 2.38  PT= 48.4%  SL= 50.4%  Reg=  1.2%  Avg=$  -7.3  Tot=$  -166,919  PF= 0.87
  Q3 [-0.110, 0.121]                   N=22,763  MFE= 2.35  PT= 48.9%  SL= 49.5%  Reg=  1.7%  Avg=$  -5.4  Tot=$  -122,647  PF= 0.88
  Q4 [0.121, 0.471]                    N=22,785  MFE= 2.30  PT= 49.0%  SL= 49.7%  Reg=  1.3%  Avg=$  -6.4  Tot=$  -145,666  PF= 0.88
  Q5 [0.471, 14.497]                   N=22,793  MFE= 2.51  PT= 48.9%  SL= 49.3%  Reg=  1.7%  Avg=$  -6.8  Tot=$  -155,100  PF= 0.87

====================================================================================================

```


## Analysis 7: Cohen's d Full Scan

```
====================================================================================================
ANALYSIS 7: Cohen's d scan — all features, PT vs SL at bracket 075_075
====================================================================================================

  113,966 trades
  PT-first: 55,459 (48.7%)
  SL-first: 56,819 (49.9%)
  Neither:  1,688

  Testing 85 features

Feature                                       d        PT avg        SL avg  Flag
----------------------------------------------------------------------------------------------------
two_bar_close_vs_open_pct                -0.052       +0.5961       +0.6112  ·
bar1_close_vs_flip_close_atr             -0.037       +0.2315       +0.2649  
two_bar_body_atr                         -0.032       +1.1986       +1.2327  
micro_range_compression_5s               -0.019       +1.0906       +1.1007  
high_vol_bar_count_10                    +0.018       +1.2578       +1.2362  
micro_max_retracement_5s                 -0.016       +0.9612       +0.9730  
ema_spread_15m_atr                       -0.015       +4.2463       +4.2695  
bar1_body_pct                            -0.015       +0.4462       +0.4501  
flip_close_location                      +0.014       +0.5065       +0.5007  
bar1_lower_wick_pct                      +0.014       +0.2801       +0.2770  
ema3_ema9_spread_atr                     +0.014       -0.0023       -0.0099  
bar1_internals_trend_5s                  +0.014       -0.0024       -0.0119  
bar1_bullish_volume_pct                  +0.013       +0.4991       +0.4964  
vol_acceleration_5bar                    +0.013       +1.0967       +1.0785  
ema3_slope_atr                           +0.013       -0.0048       -0.0201  
bar1_vol_rank_20                         -0.013       +0.6123       +0.6161  
price_vs_sma20_atr                       +0.013       -0.0063       -0.0235  
micro_trend_12bar_5s                     +0.013       -0.0042       -0.0196  
pre_flip_5bar_range_atr                  +0.012       +1.9818       +1.9751  
flip_volume                              +0.012     +473.9123     +464.5758  
atr_at_entry                             +0.012       +6.6694       +6.6014  
atr_14                                   +0.012       +6.6694       +6.6014  
atr_at_flip                              +0.012       +6.6694       +6.6014  
sma20_vs_sma50_atr                       -0.012       +0.0813       +0.1004  
sma20_slope_atr                          -0.011       +0.0098       +0.0155  
bar1_close_location                      +0.011       +0.5077       +0.5043  
two_bar_volume_total                     +0.011     +967.7195     +951.9301  
micro_hh_count_12_5s                     +0.011       +4.8181       +4.7964  
bar1_body_atr                            -0.010       +0.5366       +0.5424  
sma50_slope_atr                          -0.010       +0.0571       +0.0671  
price_vs_sma20_5m_atr                    -0.010       +0.2443       +0.2849  
two_bar_vol_vs_40avg                     +0.010       +1.2505       +1.2408  
regime_flips_last_60min                  +0.010       +5.4263       +5.4083  
minutes_since_rth_open                   -0.010     +178.5043     +182.5770  
distance_from_session_low_atr            -0.009      +15.1071      +15.2524  
bar1_volume                              +0.008     +493.8072     +487.3543  
vol_1m_20avg                             +0.008     +406.2917     +401.6261  
flip_bar_bullish_volume_pct              +0.008       +0.4976       +0.4956  
avg_regime_duration_last_5               -0.008      +12.8715      +12.9098  
pre_flip_volume_trend                    +0.007       +1.0685       +1.0353  
flip_vol_vs_20avg                        +0.006       +1.1401       +1.1358  
micro_up_vol_pct_12_5s                   +0.006       +0.4996       +0.4982  
micro_vol_acceleration_5s                -0.006       +1.2252       +1.2299  
flip_range_atr                           -0.005       +1.2742       +1.2773  
vol_ratio_up_down_20bar                  +0.005       +1.1707       +1.1396  
flip_body_pct                            +0.005       +0.7439       +0.7430  
consecutive_trend_bars_pre_flip          +0.005       +1.1869       +1.1816  
bar1_internals_up_pct                    +0.005       +0.4482       +0.4471  
cumulative_volume_bias_10                -0.004       -0.0046       -0.0034  
flip_upper_wick_pct                      -0.004       +0.1267       +0.1273  
regime_flips_last_30min                  +0.004       +3.0972       +3.0918  
flip_bar_vol_rank_20                     -0.004       +0.5441       +0.5452  
bar1_vol_vs_20avg                        -0.004       +1.3419       +1.3462  
pre_flip_3bar_range_atr                  -0.004       +1.5518       +1.5537  
bar1_upper_wick_pct                      +0.003       +0.2736       +0.2729  
bar1_range_atr                           +0.003       +1.1281       +1.1220  
bar1_vol_vs_flip_vol                     -0.003       +1.3392       +1.3426  
regime_15m_duration_bars                 -0.003      +13.5068      +13.5395  
flip_low_to_bar1_high_atr                -0.002       +1.8849       +1.8900  
bar_range_5m_current_atr                 +0.002       +1.5028       +1.5008  
prior_regime_mfe_atr                     -0.002  +3718965.7922  +5895917.3602  
pre_flip_3bar_body_direction             -0.002       +0.2210       +0.2225  
ema_spread_atr                           +0.002       +1.1106       +1.1085  
regime_5m_duration_bars                  -0.002      +13.0820      +13.1055  
two_bar_range_atr                        -0.002       +1.9050       +1.9093  
micro_body_pct_avg_5s                    -0.002       +0.5565       +0.5567  
micro_hl_count_12_5s                     +0.002       +5.0882       +5.0844  
flip_body_atr                            -0.001       +0.9673       +0.9680  
distance_from_session_high_atr           +0.001      +10.9647      +10.9505  
flip_lower_wick_pct                      -0.001       +0.1290       +0.1292  
bar1_hh_amount_atr                       -0.001       +0.6107       +0.6126  
price_vs_sma50_atr                       -0.001       +0.0749       +0.0768  
ema_spread_5m_atr                        -0.001       +2.2368       +2.2370  
vol_ratio_up_down_10bar                  -0.000       +1.2734       +1.2739  
flip_close_vs_prior_close_atr            +0.000       +0.0000       +0.0000  
flip_high_vs_prior_high_atr              +0.000       +0.0000       +0.0000  
flip_low_vs_prior_low_atr                +0.000       +0.0000       +0.0000  
prior_regime_duration_bars               +0.000       +0.0000       +0.0000  
bars_since_last_flip                     +0.000       +0.0000       +0.0000  
ema3_slope_5m_atr                        +0.000       +0.0000       +0.0000  
hh_count_5m_3                            +0.000       +0.0000       +0.0000  
vol_vs_20avg_5m                          +0.000       +1.0000       +1.0000  
regime_flips_5m_last_5                   +0.000       +0.0000       +0.0000  
ema3_slope_15m_atr                       +0.000       +0.0000       +0.0000  
price_vs_sma20_15m_atr                   +0.000       +0.0000       +0.0000  

  No features with |d| >= 0.10.

  Saved: studies/1m_mtf_context/results/cohens_d_full.parquet

====================================================================================================

```


## Analysis 8: Feature Interactions

```
====================================================================================================
ANALYSIS 8: Feature Interactions (pairwise Q5)
====================================================================================================

  8 promising features:
    two_bar_close_vs_open_pct              d=-0.052
    bar1_close_vs_flip_close_atr           d=-0.037
    two_bar_body_atr                       d=-0.032
    micro_range_compression_5s             d=-0.019
    high_vol_bar_count_10                  d=+0.018
    micro_max_retracement_5s               d=-0.016
    ema_spread_15m_atr                     d=-0.015
    bar1_body_pct                          d=-0.015


--- Single-feature Q5 baseline ---

  two_bar_close_vs_open_pct Q1 (bottom) N=22,804  MFE= 2.24  PT= 48.4%  SL= 46.6%  Reg=  5.0%  Avg=$  -7.1  Tot=$  -162,623  PF= 0.86
  bar1_close_vs_flip_close_atr Q1 (bottom) N=22,794  MFE= 2.25  PT= 48.7%  SL= 46.3%  Reg=  5.0%  Avg=$  -5.7  Tot=$  -129,775  PF= 0.89
  two_bar_body_atr Q1 (bottom)         N=22,794  MFE= 2.17  PT= 48.4%  SL= 46.4%  Reg=  5.2%  Avg=$  -6.7  Tot=$  -153,690  PF= 0.87
  micro_range_compression_5s Q1 (bottom) N=22,913  MFE= 2.44  PT= 49.0%  SL= 49.3%  Reg=  1.7%  Avg=$  -6.1  Tot=$  -140,062  PF= 0.88
  high_vol_bar_count_10 Q5 (top)       N=16,042  MFE= 2.52  PT= 49.2%  SL= 49.5%  Reg=  1.4%  Avg=$  -6.2  Tot=$  -100,249  PF= 0.87
  micro_max_retracement_5s Q1 (bottom) N=22,804  MFE= 2.25  PT= 48.8%  SL= 49.5%  Reg=  1.6%  Avg=$  -7.3  Tot=$  -166,320  PF= 0.90
  ema_spread_15m_atr Q1 (bottom)       N=22,794  MFE= 2.35  PT= 50.0%  SL= 48.4%  Reg=  1.6%  Avg=$  -4.1  Tot=$   -93,691  PF= 0.94
  bar1_body_pct Q1 (bottom)            N=22,849  MFE= 2.45  PT= 49.0%  SL= 50.2%  Reg=  0.9%  Avg=$  -6.3  Tot=$  -143,270  PF= 0.88


--- Pairwise Q5 intersections ---

  micro_max_retracement_5s ∩ ema_spread_15m_atr N= 5,819  MFE= 2.08  PT= 50.8%  SL= 47.5%  Reg=  1.7%  Avg=$  -1.7  Tot=$    -9,908  PF= 0.98
  ema_spread_15m_atr ∩ bar1_body_pct   N= 4,606  MFE= 2.29  PT= 50.6%  SL= 48.3%  Reg=  1.1%  Avg=$  -3.7  Tot=$   -16,979  PF= 0.95
  high_vol_bar_count_10 ∩ micro_max_retracement_5s N= 2,931  MFE= 2.26  PT= 50.6%  SL= 47.7%  Reg=  1.7%  Avg=$  -5.1  Tot=$   -14,821  PF= 0.92
  two_bar_body_atr ∩ ema_spread_15m_atr N= 4,122  MFE= 2.06  PT= 49.9%  SL= 44.8%  Reg=  5.3%  Avg=$  -2.9  Tot=$   -12,056  PF= 0.96
  high_vol_bar_count_10 ∩ bar1_body_pct N= 3,156  MFE= 2.52  PT= 49.9%  SL= 49.4%  Reg=  0.7%  Avg=$  -5.7  Tot=$   -17,863  PF= 0.88
  bar1_close_vs_flip_close_atr ∩ ema_spread_15m_atr N= 4,449  MFE= 2.17  PT= 49.7%  SL= 45.7%  Reg=  4.7%  Avg=$  -1.3  Tot=$    -5,823  PF= 0.98
  micro_range_compression_5s ∩ ema_spread_15m_atr N= 4,634  MFE= 2.40  PT= 49.5%  SL= 48.6%  Reg=  1.9%  Avg=$  -5.0  Tot=$   -23,378  PF= 0.92
  two_bar_close_vs_open_pct ∩ ema_spread_15m_atr N= 4,087  MFE= 2.16  PT= 49.3%  SL= 45.6%  Reg=  5.0%  Avg=$  -4.9  Tot=$   -20,015  PF= 0.93
  bar1_close_vs_flip_close_atr ∩ bar1_body_pct N=   787  MFE= 5.03  PT= 49.2%  SL= 49.3%  Reg=  1.5%  Avg=$  -4.8  Tot=$    -3,813  PF= 0.85
  two_bar_close_vs_open_pct ∩ high_vol_bar_count_10 N= 2,890  MFE= 2.17  PT= 49.0%  SL= 46.3%  Reg=  4.7%  Avg=$  -7.5  Tot=$   -21,612  PF= 0.84
  micro_range_compression_5s ∩ high_vol_bar_count_10 N= 3,303  MFE= 2.46  PT= 49.0%  SL= 49.4%  Reg=  1.6%  Avg=$  -7.9  Tot=$   -26,025  PF= 0.84
  bar1_close_vs_flip_close_atr ∩ micro_max_retracement_5s N= 4,371  MFE= 2.44  PT= 48.8%  SL= 46.3%  Reg=  4.9%  Avg=$  -4.6  Tot=$   -20,153  PF= 0.93
  micro_range_compression_5s ∩ bar1_body_pct N= 4,499  MFE= 2.42  PT= 48.8%  SL= 50.3%  Reg=  0.9%  Avg=$  -8.2  Tot=$   -36,813  PF= 0.85
  high_vol_bar_count_10 ∩ ema_spread_15m_atr N= 6,340  MFE= 2.44  PT= 48.8%  SL= 50.0%  Reg=  1.3%  Avg=$  -8.5  Tot=$   -53,694  PF= 0.86
  micro_max_retracement_5s ∩ bar1_body_pct N= 4,760  MFE= 2.55  PT= 48.8%  SL= 50.2%  Reg=  1.1%  Avg=$  -6.4  Tot=$   -30,496  PF= 0.91
  bar1_close_vs_flip_close_atr ∩ high_vol_bar_count_10 N= 3,246  MFE= 2.21  PT= 48.7%  SL= 46.8%  Reg=  4.4%  Avg=$  -8.5  Tot=$   -27,593  PF= 0.82
  micro_range_compression_5s ∩ micro_max_retracement_5s N= 4,669  MFE= 2.16  PT= 48.6%  SL= 49.3%  Reg=  2.1%  Avg=$  -7.0  Tot=$   -32,704  PF= 0.90
  bar1_close_vs_flip_close_atr ∩ micro_range_compression_5s N= 4,498  MFE= 2.17  PT= 48.5%  SL= 46.0%  Reg=  5.4%  Avg=$  -6.8  Tot=$   -30,652  PF= 0.87
  two_bar_body_atr ∩ high_vol_bar_count_10 N= 2,695  MFE= 2.08  PT= 48.4%  SL= 46.6%  Reg=  5.0%  Avg=$  -9.4  Tot=$   -25,396  PF= 0.80
  two_bar_body_atr ∩ bar1_body_pct     N= 4,036  MFE= 2.70  PT= 48.4%  SL= 49.5%  Reg=  2.2%  Avg=$  -7.7  Tot=$   -31,162  PF= 0.85
  two_bar_close_vs_open_pct ∩ micro_range_compression_5s N= 4,857  MFE= 2.21  PT= 48.4%  SL= 46.4%  Reg=  5.3%  Avg=$  -8.2  Tot=$   -39,815  PF= 0.83
  two_bar_close_vs_open_pct ∩ two_bar_body_atr N=19,328  MFE= 2.19  PT= 48.3%  SL= 46.1%  Reg=  5.6%  Avg=$  -6.9  Tot=$  -132,574  PF= 0.87
  two_bar_close_vs_open_pct ∩ bar1_close_vs_flip_close_atr N=16,104  MFE= 2.23  PT= 48.3%  SL= 45.4%  Reg=  6.3%  Avg=$  -6.5  Tot=$  -104,827  PF= 0.87
  bar1_close_vs_flip_close_atr ∩ two_bar_body_atr N=14,591  MFE= 2.19  PT= 48.2%  SL= 45.1%  Reg=  6.7%  Avg=$  -6.3  Tot=$   -91,474  PF= 0.88
  two_bar_close_vs_open_pct ∩ micro_max_retracement_5s N= 3,863  MFE= 2.43  PT= 48.1%  SL= 46.2%  Reg=  5.7%  Avg=$  -6.2  Tot=$   -24,140  PF= 0.91
  two_bar_body_atr ∩ micro_max_retracement_5s N= 4,281  MFE= 2.37  PT= 48.0%  SL= 46.4%  Reg=  5.5%  Avg=$  -6.5  Tot=$   -27,683  PF= 0.91
  two_bar_close_vs_open_pct ∩ bar1_body_pct N= 3,691  MFE= 2.83  PT= 47.8%  SL= 50.8%  Reg=  1.3%  Avg=$  -9.4  Tot=$   -34,747  PF= 0.81
  two_bar_body_atr ∩ micro_range_compression_5s N= 5,129  MFE= 2.09  PT= 47.8%  SL= 46.9%  Reg=  5.3%  Avg=$  -8.7  Tot=$   -44,525  PF= 0.82


--- Triple Q5 intersections (top 10 by PT%) ---

  bar1_close_v∩micro_max_re∩bar1_body_pc N=    55  MFE=37.70  PT= 56.4%  SL= 43.6%  Reg=  0.0%  Avg=$  +7.9  Tot=$      +436  PF= 1.21
  bar1_close_v∩high_vol_bar∩bar1_body_pc N=   134  MFE= 2.40  PT= 54.5%  SL= 44.8%  Reg=  0.7%  Avg=$  -0.0  Tot=$        -7  PF= 1.00
  bar1_close_v∩ema_spread_1∩bar1_body_pc N=   129  MFE= 2.36  PT= 51.9%  SL= 47.3%  Reg=  0.8%  Avg=$  +4.7  Tot=$      +602  PF= 1.11
  micro_max_re∩ema_spread_1∩bar1_body_pc N= 1,197  MFE= 2.14  PT= 51.5%  SL= 47.3%  Reg=  1.3%  Avg=$  +0.6  Tot=$      +772  PF= 1.01
  high_vol_bar∩micro_max_re∩bar1_body_pc N=   590  MFE= 2.38  PT= 51.4%  SL= 47.1%  Reg=  1.5%  Avg=$  -1.7  Tot=$    -1,000  PF= 0.97
  two_bar_clos∩ema_spread_1∩bar1_body_pc N=   612  MFE= 2.27  PT= 50.5%  SL= 48.5%  Reg=  1.0%  Avg=$  -8.2  Tot=$    -5,014  PF= 0.88
  two_bar_clos∩micro_range_∩bar1_body_pc N=   809  MFE= 2.46  PT= 50.4%  SL= 48.3%  Reg=  1.2%  Avg=$  -3.1  Tot=$    -2,522  PF= 0.93
  two_bar_body∩ema_spread_1∩bar1_body_pc N=   730  MFE= 2.08  PT= 50.4%  SL= 47.0%  Reg=  2.6%  Avg=$  -4.8  Tot=$    -3,485  PF= 0.93
  two_bar_body∩micro_max_re∩ema_spread_1 N= 1,054  MFE= 1.92  PT= 50.4%  SL= 44.5%  Reg=  5.1%  Avg=$  +3.4  Tot=$    +3,636  PF= 1.04
  high_vol_bar∩micro_max_re∩ema_spread_1 N= 1,388  MFE= 2.24  PT= 50.4%  SL= 47.9%  Reg=  1.7%  Avg=$  -7.2  Tot=$    -9,995  PF= 0.91

====================================================================================================

```
