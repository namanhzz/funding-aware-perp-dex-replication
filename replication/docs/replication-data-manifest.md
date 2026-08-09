# Replication data manifest

Final holdout candles and funding were downloaded from the official Hyperliquid info API.
Training fill curves were produced from pre-2026 official fills joined to the local L2 panel.
The manifest records exact file hashes; source reconstruction commands are in the repository documentation.

| File | Status | Rows | Size (bytes) | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `data/clean/eth-hyperliquid-candles-15m-final-20260618-20260731.parquet` | available | 4217 | 183557 | `6b20c4453b7b9a25e28bdfc48018ab95208b4416c336a36306b1349351476f9e` |
| `data/clean/btc-hyperliquid-candles-15m-final-20260618-20260731.parquet` | available | 4217 | 205689 | `5c02e9fd80b1f15bc84aefb278f2319fea3fdd9d5c41b74af1777b438532a637` |
| `data/clean/sol-hyperliquid-candles-15m-final-20260618-20260731.parquet` | available | 4216 | 204261 | `4bfe830f5a36cf8dd4292efe9ca5f8ff70c9284965bc045325d0c3069c30097e` |
| `data/clean/eth-funding-1h-final-20260618-20260731.parquet` | available | 1056 | 24265 | `0139dffd5a02e898342e45d5d4754c335d57b1ab3cc1c08ec1083c764535e7a0` |
| `data/clean/btc-funding-1h-final-20260618-20260731.parquet` | available | 1056 | 24974 | `3b2a5c1f0df8868338f0a8f3d2908892c8e23f7a1b9bd4a30eafe6890819a311` |
| `data/clean/sol-funding-1h-final-20260618-20260731.parquet` | available | 1056 | 26459 | `6cd3f3ad13dcd82635a43277304a87dfe19354cd5db3956388d10e4e9f57ed96` |
| `data/clean/eth-binance-mark-candles-1m-final-20260618-20260731.parquet` | available | 63360 | 2791237 | `76c4a5cf6f79ee84323c8f39afa8254a75e7f06881fd55ddb926787ef50461c7` |
| `data/clean/btc-binance-mark-candles-1m-final-20260618-20260731.parquet` | available | 63360 | 2897570 | `03b0d9007277bdb221042224a2f4b3870b9f1e666515e2c0821e01776cc77d29` |
| `data/clean/sol-binance-mark-candles-1m-final-20260618-20260731.parquet` | available | 63360 | 2516704 | `7f96ea1a4d93e1c3858c36c163e9d9fddbab59dba684491e88c82ff840c1f34d` |
| `data/clean/eth-causal-intrabar-bridge-1m-final-20260618-20260731.parquet` | available | 63255 | 3202506 | `31add69b3dd51773a76ba012e778c744ad1a6ea146774bc768789a17cabaaeb6` |
| `data/clean/btc-causal-intrabar-bridge-1m-final-20260618-20260731.parquet` | available | 63255 | 3211873 | `a4034ee1e29a2025ef0bdb8081aaaed21cad6cb096215fadd5993dc1a1f5b493` |
| `data/clean/sol-causal-intrabar-bridge-1m-final-20260618-20260731.parquet` | available | 63240 | 3109560 | `8597e0d693922dcbab8a069db6363ea8d926378924b0b81b19e658f31bea3655` |
| `data/clean/eth-hyperliquid-candles-1h-extended-20260115-20260731.parquet` | available | 4752 | 234837 | `004f6e26218e443bed306c69df42606bfb1b33dce3ade0ef4e7b673384e655cc` |
| `data/clean/btc-hyperliquid-candles-1h-extended-20260115-20260731.parquet` | available | 4752 | 259625 | `ca8235dd5633971036e993e66a63ce60db123e5676644a3f49279d989c00bbda` |
| `data/clean/sol-hyperliquid-candles-1h-extended-20260115-20260731.parquet` | available | 4752 | 249232 | `3209ced752a7e98e73b84dd96c005cc34b98148e5185a91a5fef2b97d243f84d` |
| `data/clean/eth-funding-1h-extended-20260115-20260731.parquet` | available | 4752 | 112940 | `05d9d79a6d7551e36b0acbb1eab7025214fb93266b187e56a9bdf6188e2cfd92` |
| `data/clean/btc-funding-1h-extended-20260115-20260731.parquet` | available | 4752 | 115919 | `49b27c9dff350209cea92d8868341a20690d4bcaddc1bc6fc916f7057f77b0e3` |
| `data/clean/sol-funding-1h-extended-20260115-20260731.parquet` | available | 4752 | 120170 | `1e5a640459ea93f68e6f04355ccb7c863ba4ad108d3197150a9e5f939c3534f4` |
| `data/clean/eth-binance-mark-candles-1m-extended-20260115-20260731.parquet` | available | 285120 | 11544759 | `462309a55caa1b45a2123952c7ddcab2849970e390932aca8cd7587e458e6f81` |
| `data/clean/btc-binance-mark-candles-1m-extended-20260115-20260731.parquet` | available | 285120 | 11868592 | `9cac35795352ba444ce08c55119784bb66e5892c13c27ddd5d6ac91862897a06` |
| `data/clean/sol-binance-mark-candles-1m-extended-20260115-20260731.parquet` | available | 285120 | 10722483 | `c0db03e4f6eb8726c7a55cdaf178498c135fd94be1e948f7d2214a43e7783e00` |
| `data/clean/eth-causal-intrabar-bridge-1m-extended-20260115-20260731.parquet` | available | 285120 | 13185301 | `d91247c8b8ceae61eca0202e3f28ef540b2382de3ed1f2a515f476a90e3f94db` |
| `data/clean/btc-causal-intrabar-bridge-1m-extended-20260115-20260731.parquet` | available | 285120 | 13204965 | `00457e7d26bbe1a59028783dd2226907f1cacee24f600e5a6a642320f20c86be` |
| `data/clean/sol-causal-intrabar-bridge-1m-extended-20260115-20260731.parquet` | available | 285120 | 12715312 | `86d3dd6c7a295f9f4495df9f4ffc6a2f6980e713cc4e8f91477c3bbb23e41ba3` |
| `results/calibration-eth.json` | available |  | 2060 | `223ecd5e97ff1721e1dc231f0902af1f2633f564c459a1eb5c47d94ae44f12f1` |
| `results/calibration-btc.json` | available |  | 2063 | `2476ac52ff7049ab089d036da84443a276d3e9242d26e6b696a80da9c64f57e5` |
| `results/calibration-sol.json` | available |  | 2056 | `50fb01357fd67549abe28d647f455564263f395402fe89bbcb6ebc3b3ba1a363` |
| `results/fill-intensity-eth-volume-minute-1eth-train.json` | available |  | 4365 | `01e1490beb67a7b655c8de75c3ac6cc1e0d5757ce1c998aa2cc6df467f4fd64e` |
| `results/fill-intensity-btc-volume-minute-0p05btc-train.json` | available |  | 4372 | `8afa51f3011466f818f70423bb035926dee096fa0ea947f06cb67a0c257f6b87` |
| `results/fill-intensity-sol-volume-minute-25sol-train.json` | available |  | 4160 | `a13e5c5a3090f256e2ee19874042b0c0679a3d3facee47da340581943c1f354b` |
| `results/fill-intensity-eth-minute-hit-train.json` | available |  | 4367 | `632287de39d3e03e0731883aadf0d8c77282eba1f280acba7e27c172e26095c5` |
| `results/fill-intensity-btc-minute-hit-train.json` | available |  | 4369 | `6d44a88b6a9fb53e449dcbdf22e7e9e7863a443fbc8387f65573f78fc43c5f28` |
| `results/fill-intensity-sol-minute-hit-train.json` | available |  | 4167 | `7b6c614d39668a33d649f9843c1744f2ded0a02b2516e9c1c9ab50091ffdc32f` |
| `results/predeclared-development-selection-2026.json` | available |  | 156569 | `63ad182925de677f6e376448137005fb4d9dad59ade17627c518cee694686ab2` |
| `results/development-risk-frontier-2026-sol.json` | available |  | 116116 | `3cd4d99c042df3662ed8c430d13c27b7f20c63f901f9c3d98e3a3f98422bacc1` |
| `results/final-holdout-2026-100.json` | available |  | 2765312 | `da460c87a4f89056ee4d837348a6ef12a258f61b7abc6fc6c9cded4abb517949` |
| `results/final-holdout-2026-minute-hit-100.json` | available |  | 2764466 | `9acea5832789facdefa0e9671aa730ee7c9603ca91860b115eb1ce69708991a3` |
| `results/final-holdout-2026-conservative-execution-100.json` | available |  | 2775384 | `8baa253d7a36eb2d60275c7e864f99842dbc67925309b92ff17aab439d11e461` |
| `results/final-holdout-2026-zero-fee-100.json` | available |  | 2756361 | `b44d7eea689cd3676ea8d99297f7ab358da5da77baac5f31910f98f7e7f095b7` |
| `results/final-holdout-2026-rebate-100.json` | available |  | 2770570 | `92acf7b43b5ebee035c4faf9959cfbc4ee0b4deb86fafb0f698ef96b95367444` |
| `results/final-holdout-2026-continuous-funding-100.json` | available |  | 2766326 | `54b529a913b576d4bfe8ef9f96df3dc024744cf1414cf93efb7034be694ba68d` |
| `results/final-holdout-2026-intrabar-bridge-100.json` | available |  | 2765399 | `1250b986edd04c3ac69669135eeba21f721f6449b5a2a4549a05e4db385876a0` |
| `results/final-holdout-2026-sol-risk-frontier-100.json` | available |  | 6795997 | `4e0060d436b1cde556ba62b7d205f3b3839634a0455be924bc9e1b40121358b1` |
| `results/sol-risk-frontier-summary.json` | available |  | 28254 | `c53b3e20c21d64fd33f3756ecf27b256c39c1b6a9261609e9264847787460097` |
| `results/extended-window-2026-100.json` | available |  | 9709821 | `60562968187d339c56b2e1deb21d426230b3b0e4a5cc43776e10ab92f81d8a69` |
| `results/extended-window-2026-sol-risk-frontier-100.json` | available |  | 23839167 | `5354e084252edca0594807f63fdfd2c512ac57081fd823a48bbaf29bff106216` |
| `results/extended-window-2026-sol-risk-frontier-summary.json` | available |  | 83653 | `d64cc0b37a1a0b0725026bc8e443fd808ccfd25fd52d9dbfd0168ead37173272` |
| `configs/final_holdout_2026_design.yaml` | available |  | 3326 | `5ec33581a47c8de335392184a964ba8e686b920bec1aa51fcf543a57c5f74331` |
| `configs/final_holdout_2026_100.yaml` | available |  | 3075 | `3221105bbc8ff0b27658ed2de5a035f702ef2dd79c173a3ccf0660fa9b69b607` |
| `configs/final_holdout_2026_minute_hit_100.yaml` | available |  | 3300 | `102d631a9a995224dcf15b9eb79d1fe755c96122062469c681b60c189d308ddd` |
| `configs/final_holdout_2026_conservative_execution_100.yaml` | available |  | 3075 | `26c3c2018292fa1c0b7ec4d1baba045bcf6052fb3c19b45c913c73a7c0625de3` |
| `configs/final_holdout_2026_zero_fee_100.yaml` | available |  | 3063 | `92216da4b0c585d04ad06d96556b7fe9e9ba943ee63e0d693a6fe0c01356520b` |
| `configs/final_holdout_2026_rebate_100.yaml` | available |  | 3078 | `8671d790b3f7c381f60f12f193b5576a48732c3507548a48d0b7d136d37116c6` |
| `configs/development_risk_frontier_2026.yaml` | available |  | 1805 | `28493935e1b4d23af9303efcad4f91ebf9fbe8792f049e3dfc122a547db5dc0d` |
| `configs/final_holdout_2026_continuous_funding_100.yaml` | available |  | 3060 | `888c5c1f0f1a0ccbfde981fb998b4c153b5efb96ad30975c4761b9ef6da5aa98` |
| `configs/final_holdout_2026_intrabar_bridge_100.yaml` | available |  | 3081 | `0a24bcb76521460d8bffab9b6055e2e955003ee854b5d7a43844ccc3c2bd7d45` |
| `configs/final_holdout_2026_sol_risk_frontier_100.yaml` | available |  | 6238 | `ba19eca3a5377834cc8b2956b228b907275245254b321ec302b99910cb517f6c` |
| `configs/extended_window_2026_100.yaml` | available |  | 3327 | `53dc58c19a5b33d6989508a7f3d3f04e58f49f483ca5dc55ba3a753d8bb89774` |
| `configs/extended_window_2026_sol_risk_frontier_100.yaml` | available |  | 6317 | `8756887027bcc97960d63986aca7b4d88f4b2753c2a2be6c1d29cbc0bbbdf1d7` |

## Source URLs

- hyperliquid_info_api: https://api.hyperliquid.xyz/info
- hyperliquid_historical_docs: https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data
- binance_usdm_api: https://fapi.binance.com/fapi/v1/markPriceKlines
