# Encoding DB 人工抽查报告 — py32f420

- L1 覆盖率:**87.4%**(465/532,InitTypeDef 口径)
- 本报告只列**需要人眼**的条目(置信度 llm_inferred / c_placement / inherited / manual);direct(头文件链路机械证明 + fixtures 回归)只给计数。
- 写法:`符号 → 寄存器.字段 = 字段内值`(值未左移)。

## ADC

置信度计数:direct=56, inherited=99, llm_inferred=7

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| ConversionGroup | `ADC_INJECTED_GROUP` | CR.JADSTP | 1 | llm_inferred |  |
| ConversionGroup | `ADC_REGULAR_GROUP` | CR.ADSTP | 1 | llm_inferred |  |
| DMAAccessMode | `ADC_DMAACCESSMODE_12_10_BITS` | CCR.MDMA | 2 | inherited | DMA multimode enabled (one DMA channel for both AD |
| DMAAccessMode | `ADC_DMAACCESSMODE_8_6_BITS` | CCR.MDMA | 3 | inherited | DMA multimode enabled (one DMA channel for both AD |
| DMAAccessMode | `ADC_DMAACCESSMODE_DISABLED` | CCR.MDMA | 0 | inherited | DMA multimode disabled: each ADC uses its own DMA  |
| DataAlign | `ADC_DATAALIGN_LEFT` | CFGR.ALIGN | 1 | inherited | ADC conversion data alignment: left aligned (align |
| DataAlign | `ADC_DATAALIGN_RIGHT` | CFGR.ALIGN | 0 | inherited | ADC conversion data alignment: right aligned (alig |
| ExternalTrigConv | `ADC_EXTERNALTRIG_T1_CC1` | CFGR.EXTEN | 1 | inherited | ADC group regular conversion trigger from external |
| ExternalTrigConv | `ADC_SOFTWARE_START` | CFGR.EXTEN | 0 | inherited | ADC group regular conversion trigger software star |
| ExternalTrigConvEdge | `ADC_EXTERNALTRIGCONVEDGE_FALLING` | CFGR.EXTEN | 2 | inherited | ADC group regular conversion trigger polarity set  |
| ExternalTrigConvEdge | `ADC_EXTERNALTRIGCONVEDGE_NONE` | CFGR.EXTEN | 0 | inherited | ADC group regular trigger disabled (SW start) |
| ExternalTrigConvEdge | `ADC_EXTERNALTRIGCONVEDGE_RISING` | CFGR.EXTEN | 1 | inherited | ADC group regular conversion trigger polarity set  |
| ExternalTrigConvEdge | `ADC_EXTERNALTRIGCONVEDGE_RISINGFALLING` | CFGR.EXTEN | 3 | inherited | ADC group regular conversion trigger polarity set  |
| ExternalTrigInjecConv | `ADC_EXTERNALTRIGINJEC_T1_TRGO` | JSQR.JEXTEN | 1 | inherited | ADC group injected conversion trigger from externa |
| ExternalTrigInjecConv | `ADC_INJECTED_SOFTWARE_START` | JSQR.JEXTEN | 0 | inherited | ADC group injected conversion trigger software sta |
| ExternalTrigInjecConvEdge | `ADC_EXTERNALTRIGINJECCONV_EDGE_FALLING` | JSQR.JEXTEN | 2 | inherited | Injected conversions trigger polarity set to falli |
| ExternalTrigInjecConvEdge | `ADC_EXTERNALTRIGINJECCONV_EDGE_NONE` | JSQR.JEXTEN | 0 | inherited | Injected conversions trigger disabled (SW start) |
| ExternalTrigInjecConvEdge | `ADC_EXTERNALTRIGINJECCONV_EDGE_RISING` | JSQR.JEXTEN | 1 | inherited | Injected conversions trigger polarity set to risin |
| ExternalTrigInjecConvEdge | `ADC_EXTERNALTRIGINJECCONV_EDGE_RISINGFALLING` | JSQR.JEXTEN | 3 | inherited | Injected conversions trigger polarity set to both  |
| FilteringConfig | `ADC_AWD_FILTERING_2SAMPLES` | TR1.AWDFILT | 1 | inherited | ADC AWD 2 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_3SAMPLES` | TR1.AWDFILT | 2 | inherited | ADC AWD 3 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_4SAMPLES` | TR1.AWDFILT | 3 | inherited | ADC AWD 4 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_5SAMPLES` | TR1.AWDFILT | 4 | inherited | ADC AWD 5 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_6SAMPLES` | TR1.AWDFILT | 5 | inherited | ADC AWD 6 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_7SAMPLES` | TR1.AWDFILT | 6 | inherited | ADC AWD 7 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_8SAMPLES` | TR1.AWDFILT | 7 | inherited | ADC AWD 8 consecutives out-of-window samples to ra |
| FilteringConfig | `ADC_AWD_FILTERING_NONE` | TR1.AWDFILT | 0 | inherited | ADC AWD no filtering, one out-of-window sample to  |
| InjectedOffsetSign | `ADC_OFFSET_SIGN_NEGATIVE` | OFR1.OFFSETPOS | 0 | inherited |  |
| InjectedOffsetSign | `ADC_OFFSET_SIGN_POSITIVE` | OFR1.OFFSETPOS | 1 | inherited |  |
| InjectedSamplingTime | `ADC_SAMPLETIME_12CYCLES_5` | SMPR2.SMP10 | 2 | inherited | Sampling time 12.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_247CYCLES_5` | SMPR2.SMP10 | 6 | inherited | Sampling time 247.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_24CYCLES_5` | SMPR2.SMP10 | 3 | inherited | Sampling time 24.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_2CYCLES_5` | SMPR2.SMP10 | 0 | inherited | Sampling time 2.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_47CYCLES_5` | SMPR2.SMP10 | 4 | inherited | Sampling time 47.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_640CYCLES_5` | SMPR2.SMP10 | 7 | inherited | Sampling time 640.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_6CYCLES_5` | SMPR2.SMP10 | 1 | inherited | Sampling time 6.5 ADC clock cycles |
| InjectedSamplingTime | `ADC_SAMPLETIME_92CYCLES_5` | SMPR2.SMP10 | 5 | inherited | Sampling time 92.5 ADC clock cycles |
| OffsetNumber | `ADC_OFFSET_2` | OFR1.OFFSET1_EN | 1 | llm_inferred |  |
| OffsetNumber | `ADC_OFFSET_3` | OFR2.OFFSET2_EN | 1 | llm_inferred |  |
| OffsetNumber | `ADC_OFFSET_4` | OFR3.OFFSET3_EN | 1 | llm_inferred |  |
| OffsetSign | `ADC_OFFSET_SIGN_NEGATIVE` | OFR1.OFFSETPOS | 0 | inherited |  |
| OffsetSign | `ADC_OFFSET_SIGN_POSITIVE` | OFR1.OFFSETPOS | 1 | inherited |  |
| Overrun | `ADC_OVR_DATA_OVERWRITTEN` | CFGR.OVRMOD | 1 | inherited | ADC group regular behavior in case of overrun: dat |
| Overrun | `ADC_OVR_DATA_PRESERVED` | CFGR.OVRMOD | 0 | inherited | ADC group regular behavior in case of overrun: dat |
| Ratio | `ADC_OVERSAMPLING_RATIO_128` | CFGR2.OVSR | 6 | inherited | ADC oversampling ratio 128 |
| Ratio | `ADC_OVERSAMPLING_RATIO_128` | CFGR2.OVSR | 6 | inherited | ADC oversampling ratio 128 |
| Ratio | `ADC_OVERSAMPLING_RATIO_16` | CFGR2.OVSR | 3 | inherited | ADC oversampling ratio 16 |
| Ratio | `ADC_OVERSAMPLING_RATIO_16` | CFGR2.OVSR | 3 | inherited | ADC oversampling ratio 16 |
| Ratio | `ADC_OVERSAMPLING_RATIO_2` | CFGR2.OVSR | 0 | inherited | ADC oversampling ratio 2 |
| Ratio | `ADC_OVERSAMPLING_RATIO_2` | CFGR2.OVSR | 0 | inherited | ADC oversampling ratio 2 |
| Ratio | `ADC_OVERSAMPLING_RATIO_256` | CFGR2.OVSR | 7 | inherited | ADC oversampling ratio 256 |
| Ratio | `ADC_OVERSAMPLING_RATIO_256` | CFGR2.OVSR | 7 | inherited | ADC oversampling ratio 256 |
| Ratio | `ADC_OVERSAMPLING_RATIO_32` | CFGR2.OVSR | 4 | inherited | ADC oversampling ratio 32 |
| Ratio | `ADC_OVERSAMPLING_RATIO_32` | CFGR2.OVSR | 4 | inherited | ADC oversampling ratio 32 |
| Ratio | `ADC_OVERSAMPLING_RATIO_4` | CFGR2.OVSR | 1 | inherited | ADC oversampling ratio 4 |
| Ratio | `ADC_OVERSAMPLING_RATIO_4` | CFGR2.OVSR | 1 | inherited | ADC oversampling ratio 4 |
| Ratio | `ADC_OVERSAMPLING_RATIO_64` | CFGR2.OVSR | 5 | inherited | ADC oversampling ratio 64 |
| Ratio | `ADC_OVERSAMPLING_RATIO_64` | CFGR2.OVSR | 5 | inherited | ADC oversampling ratio 64 |
| Ratio | `ADC_OVERSAMPLING_RATIO_8` | CFGR2.OVSR | 2 | inherited | ADC oversampling ratio 8 |
| Ratio | `ADC_OVERSAMPLING_RATIO_8` | CFGR2.OVSR | 2 | inherited | ADC oversampling ratio 8 |
| Resolution | `ADC_RESOLUTION_10B` | CFGR.RES | 1 | inherited | ADC resolution 10 bits |
| Resolution | `ADC_RESOLUTION_12B` | CFGR.RES | 0 | inherited | ADC resolution 12 bits |
| Resolution | `ADC_RESOLUTION_6B` | CFGR.RES | 3 | inherited | ADC resolution 6 bits |
| Resolution | `ADC_RESOLUTION_8B` | CFGR.RES | 2 | inherited | ADC resolution 8 bits |
| RightBitShift | `ADC_RIGHTBITSHIFT_1` | CFGR2.OVSS | 1 | inherited | ADC oversampling right shift of 1 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_1` | CFGR2.OVSS | 1 | inherited | ADC oversampling right shift of 1 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_2` | CFGR2.OVSS | 2 | inherited | ADC oversampling right shift of 2 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_2` | CFGR2.OVSS | 2 | inherited | ADC oversampling right shift of 2 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_3` | CFGR2.OVSS | 3 | inherited | ADC oversampling right shift of 3 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_3` | CFGR2.OVSS | 3 | inherited | ADC oversampling right shift of 3 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_4` | CFGR2.OVSS | 4 | inherited | ADC oversampling right shift of 4 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_4` | CFGR2.OVSS | 4 | inherited | ADC oversampling right shift of 4 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_5` | CFGR2.OVSS | 5 | inherited | ADC oversampling right shift of 5 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_5` | CFGR2.OVSS | 5 | inherited | ADC oversampling right shift of 5 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_6` | CFGR2.OVSS | 6 | inherited | ADC oversampling right shift of 6 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_6` | CFGR2.OVSS | 6 | inherited | ADC oversampling right shift of 6 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_7` | CFGR2.OVSS | 7 | inherited | ADC oversampling right shift of 7 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_7` | CFGR2.OVSS | 7 | inherited | ADC oversampling right shift of 7 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_8` | CFGR2.OVSS | 8 | inherited | ADC oversampling right shift of 8 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_8` | CFGR2.OVSS | 8 | inherited | ADC oversampling right shift of 8 ranks |
| RightBitShift | `ADC_RIGHTBITSHIFT_NONE` | CFGR2.OVSS | 0 | inherited | ADC oversampling no shift |
| RightBitShift | `ADC_RIGHTBITSHIFT_NONE` | CFGR2.OVSS | 0 | inherited | ADC oversampling no shift |
| SamplingTime | `ADC_SAMPLETIME_12CYCLES_5` | SMPR2.SMP10 | 2 | inherited | Sampling time 12.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_247CYCLES_5` | SMPR2.SMP10 | 6 | inherited | Sampling time 247.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_24CYCLES_5` | SMPR2.SMP10 | 3 | inherited | Sampling time 24.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_2CYCLES_5` | SMPR2.SMP10 | 0 | inherited | Sampling time 2.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_47CYCLES_5` | SMPR2.SMP10 | 4 | inherited | Sampling time 47.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_640CYCLES_5` | SMPR2.SMP10 | 7 | inherited | Sampling time 640.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_6CYCLES_5` | SMPR2.SMP10 | 1 | inherited | Sampling time 6.5 ADC clock cycles |
| SamplingTime | `ADC_SAMPLETIME_92CYCLES_5` | SMPR2.SMP10 | 5 | inherited | Sampling time 92.5 ADC clock cycles |
| ScanConvMode | `ADC_SCAN_DISABLE` | SQR1.L | 0 | llm_inferred |  |
| SingleDiff | `ADC_DIFFERENTIAL_ENDED` | DIFSEL.DIFSEL | 1 | llm_inferred |  |
| TriggeredMode | `ADC_TRIGGEREDMODE_MULTI_TRIGGER` | CFGR2.TROVS | 1 | inherited | ADC oversampling discontinuous mode: discontinuous |
| TriggeredMode | `ADC_TRIGGEREDMODE_SINGLE_TRIGGER` | CFGR2.TROVS | 0 | inherited | ADC oversampling discontinuous mode: continuous mo |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_10CYCLES` | CCR.DELAY | 9 | inherited | ADC multimode delay between two sampling phases: 1 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_11CYCLES` | CCR.DELAY | 10 | inherited | ADC multimode delay between two sampling phases: 1 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_12CYCLES` | CCR.DELAY | 11 | inherited | ADC multimode delay between two sampling phases: 1 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_1CYCLE` | CCR.DELAY | 0 | inherited | ADC multimode delay between two sampling phases: 1 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_2CYCLES` | CCR.DELAY | 1 | inherited | ADC multimode delay between two sampling phases: 2 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_3CYCLES` | CCR.DELAY | 2 | inherited | ADC multimode delay between two sampling phases: 3 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_4CYCLES` | CCR.DELAY | 3 | inherited | ADC multimode delay between two sampling phases: 4 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_5CYCLES` | CCR.DELAY | 4 | inherited | ADC multimode delay between two sampling phases: 5 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_6CYCLES` | CCR.DELAY | 5 | inherited | ADC multimode delay between two sampling phases: 6 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_7CYCLES` | CCR.DELAY | 6 | inherited | ADC multimode delay between two sampling phases: 7 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_8CYCLES` | CCR.DELAY | 7 | inherited | ADC multimode delay between two sampling phases: 8 |
| TwoSamplingDelay | `ADC_TWOSAMPLINGDELAY_9CYCLES` | CCR.DELAY | 8 | inherited | ADC multimode delay between two sampling phases: 9 |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| GainCompensation | 0..16393 | GCOMP.GCOMPCOEFF | IS_ADC_GAIN_COMPENSATION |
| NbrOfConversion | 1..16 | SQR1.L | IS_ADC_REGULAR_NB_CONV |
| NbrOfDiscConversion | 1..8 | 待定 | IS_ADC_REGULAR_DISCONT_NUMBER |
| InjectedNbrOfConversion | 1..4 | 待定 | IS_ADC_INJECTED_NB_CONV |
| LowPowerAutoWait | 0..1 | 待定 | FunctionalState |
| ContinuousConvMode | 0..1 | 待定 | FunctionalState |
| DiscontinuousConvMode | 0..1 | 待定 | FunctionalState |
| DMAContinuousRequests | 0..1 | 待定 | FunctionalState |
| OversamplingMode | 0..1 | 待定 | FunctionalState |
| OffsetSaturation | 0..1 | 待定 | FunctionalState |
| ITMode | 0..1 | 待定 | FunctionalState |
| InjectedOffsetSaturation | 0..1 | 待定 | FunctionalState |
| InjectedDiscontinuousConvMode | 0..1 | 待定 | FunctionalState |
| AutoInjectedConv | 0..1 | 待定 | FunctionalState |
| InjecOversamplingMode | 0..1 | 待定 | FunctionalState |
| ScanConvMode | 0..15 | SQR1.L | llm_inferred |
| Offset | 0..4095 | OFR1.OFFSET1 | llm_inferred |
| Offset | 0..4095 | OFR2.OFFSET2 | llm_inferred |
| Offset | 0..4095 | OFR3.OFFSET3 | llm_inferred |
| Offset | 0..4095 | OFR4.OFFSET4 | llm_inferred |
| HighThreshold | 0..4095 | TR1.HT1 | llm_inferred |
| HighThreshold | 0..255 | TR2.HT2 | llm_inferred |
| HighThreshold | 0..255 | TR3.HT3 | llm_inferred |
| LowThreshold | 0..4095 | TR1.LT1 | llm_inferred |
| LowThreshold | 0..255 | TR2.LT2 | llm_inferred |
| LowThreshold | 0..255 | TR3.LT3 | llm_inferred |
| ContextQueue | 0..3 | JSQR.JL | llm_inferred |
| ContextQueue | 0..31 | JSQR.JEXTSEL | llm_inferred |
| ContextQueue | 0..3 | JSQR.JEXTEN | llm_inferred |
| ContextQueue | 0..31 | JSQR.JSQ1 | llm_inferred |
| ContextQueue | 0..31 | JSQR.JSQ2 | llm_inferred |
| ContextQueue | 0..31 | JSQR.JSQ3 | llm_inferred |
| ContextQueue | 0..31 | JSQR.JSQ4 | llm_inferred |
| ChannelCount | 0..3 | JSQR.JL | llm_inferred |
| InjectedSingleDiff | 0..65535 | DIFSEL.DIFSEL | llm_inferred |
| InjectedOffsetNumber | 0..4095 | OFR1.OFFSET1 | llm_inferred |
| InjectedOffsetNumber | 0..4095 | OFR2.OFFSET2 | llm_inferred |
| InjectedOffsetNumber | 0..4095 | OFR3.OFFSET3 | llm_inferred |
| InjectedOffsetNumber | 0..4095 | OFR4.OFFSET4 | llm_inferred |
| InjectedOffset | 0..4095 | OFR1.OFFSET1 | llm_inferred |
| InjectedOffset | 0..4095 | OFR2.OFFSET2 | llm_inferred |
| InjectedOffset | 0..4095 | OFR3.OFFSET3 | llm_inferred |
| InjectedOffset | 0..4095 | OFR4.OFFSET4 | llm_inferred |
| VrefBuf | 0..7 | CR.VREFBUFSEL | llm_inferred |
| Channel | 0..31 | SQR1.SQ1 | manual |

## COMP

置信度计数:inherited=34

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| BlankingSrce | `COMP_BLANKINGSRC_EPWM1` | CSR.BLANKSEL | 5 | inherited | Comparator output blanking source EPWM1 (specific  |
| BlankingSrce | `COMP_BLANKINGSRC_EPWM2` | CSR.BLANKSEL | 6 | inherited | Comparator output blanking source EPWM2 (specific  |
| BlankingSrce | `COMP_BLANKINGSRC_EPWM3` | CSR.BLANKSEL | 7 | inherited | Comparator output blanking source EPWM3 (specific  |
| BlankingSrce | `COMP_BLANKINGSRC_EPWM4` | CSR.BLANKSEL | 8 | inherited | Comparator output blanking source EPWM4 (specific  |
| BlankingSrce | `COMP_BLANKINGSRC_EPWM5` | CSR.BLANKSEL | 9 | inherited | Comparator output blanking source EPWM5 (specific  |
| BlankingSrce | `COMP_BLANKINGSRC_EPWM6` | CSR.BLANKSEL | 10 | inherited | Comparator output blanking source EPWM6 (specific  |
| BlankingSrce | `COMP_BLANKINGSRC_NONE` | CSR.BLANKSEL | 0 | inherited | Comparator output without blanking |
| BlankingSrce | `COMP_BLANKINGSRC_TIM1_OC5` | CSR.BLANKSEL | 1 | inherited | Comparator output blanking source TIM1 OC5 (specif |
| BlankingSrce | `COMP_BLANKINGSRC_TIM2_OC3` | CSR.BLANKSEL | 2 | inherited | Comparator output blanking source TIM2 OC3 (specif |
| BlankingSrce | `COMP_BLANKINGSRC_TIM3_OC3` | CSR.BLANKSEL | 3 | inherited | Comparator output blanking source TIM3 OC3 (specif |
| BlankingSrce | `COMP_BLANKINGSRC_TIM8_OC5` | CSR.BLANKSEL | 4 | inherited | Comparator output blanking source TIM8 OC5 (specif |
| Hysteresis | `COMP_HYSTERESIS_DISABLE` | CSR.HYST | 0 | inherited | No hysteresis |
| Hysteresis | `COMP_HYSTERESIS_ENABLE` | CSR.HYST | 1 | inherited | Hysteresis enable |
| InputMinus | `COMP_INPUT_MINUS_IO0` | CSR.INNSEL | 0 | inherited | Comparator input minus connected to IO0(pin PC3 fo |
| InputMinus | `COMP_INPUT_MINUS_IO1` | CSR.INNSEL | 1 | inherited | Comparator input minus connected to IO1(pin DAC_CH |
| InputMinus | `COMP_INPUT_MINUS_IO2` | CSR.INNSEL | 2 | inherited | Comparator input minus connected to IO2(pin DAC_CH |
| InputMinus | `COMP_INPUT_MINUS_IO3` | CSR.INNSEL | 3 | inherited | Comparator input minus connected to IO3(pin PA0 fo |
| InputPlus | `COMP_INPUT_PLUS_IO0` | CSR.INPSEL | 0 | inherited | Comparator input plus connected to IO0(pin PC2 for |
| InputPlus | `COMP_INPUT_PLUS_IO1` | CSR.INPSEL | 1 | inherited | Comparator input plus connected to IO1(pin PC1 for |
| InputPlus | `COMP_INPUT_PLUS_IO2` | CSR.INPSEL | 2 | inherited | Comparator input plus connected to IO2(pin PC0 for |
| InputPlus | `COMP_INPUT_PLUS_IO3` | CSR.INPSEL | 3 | inherited | Comparator input plus connected to IO3(pin OPA1 fo |
| InputPlus | `COMP_INPUT_PLUS_IO4` | CSR.INPSEL | 4 | inherited | Comparator input plus connected to IO4(pin TS for  |
| Mode | `COMP_POWERMODE_HIGHSPEED` | CSR.PWRMODE | 0 | inherited | High Speed |
| Mode | `COMP_POWERMODE_MEDIUMSPEED` | CSR.PWRMODE | 1 | inherited | Medium Speed |
| OutputPol | `COMP_OUTPUTPOL_INVERTED` | CSR.POLARITY | 1 | inherited | COMP output level is inverted (comparator output i |
| OutputPol | `COMP_OUTPUTPOL_NONINVERTED` | CSR.POLARITY | 0 | inherited | COMP output level is not inverted (comparator outp |
| TimAndExtiOutSel | `COMP_TIM_EXTI_OUT_FILTER` | CSR.TIM_EXTI_OUT_SEL | 1 | inherited | The comparator output to TIM or EXTI is filtered |
| TimAndExtiOutSel | `COMP_TIM_EXTI_OUT_NOFILTER` | CSR.TIM_EXTI_OUT_SEL | 0 | inherited | The comparator output to TIM or EXTI is no filtere |
| TriggerMode | `COMP_TRIGGERMODE_EVENT_RISING` | CSR.INNSEL | 2 | inherited | Comparator output triggering External Interrupt Li |
| TriggerMode | `COMP_TRIGGERMODE_EVENT_RISING_FALLING` | CSR.INNSEL | 2 | inherited | Comparator output triggering External Interrupt Li |
| TriggerMode | `COMP_TRIGGERMODE_NONE` | CSR.INNSEL | 0 | inherited | Comparator output triggering no External Interrupt |
| WindowMode | `COMP_WINDOWMODE_COMP2_INPUT_PLUS_COMMON` | CSR.WINMODE | 1 | inherited | Window mode enable: Comparators instances pair COM |
| WindowMode | `COMP_WINDOWMODE_COMP4_INPUT_PLUS_COMMON` | CSR.WINMODE | 1 | inherited | Window mode enable: Comparators instances pair COM |
| WindowMode | `COMP_WINDOWMODE_DISABLE` | CSR.WINMODE | 0 | inherited | Window mode disable: Comparators instances pair CO |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| DigitalFilter | 自由值 | FR.(整寄存器) | 扫描 |

## DAC

置信度计数:inherited=62

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| Amplitude | `DAC_LFSRUNMASK_BIT0` | CR.MAMP1 | 0 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BIT0` | CR.MAMP1 | 0 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS10_0` | CR.MAMP1 | 10 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS10_0` | CR.MAMP1 | 10 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS11_0` | CR.MAMP1 | 11 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS11_0` | CR.MAMP1 | 11 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS1_0` | CR.MAMP1 | 1 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS1_0` | CR.MAMP1 | 1 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS2_0` | CR.MAMP1 | 2 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS2_0` | CR.MAMP1 | 2 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS3_0` | CR.MAMP1 | 3 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS3_0` | CR.MAMP1 | 3 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS4_0` | CR.MAMP1 | 4 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS4_0` | CR.MAMP1 | 4 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS5_0` | CR.MAMP1 | 5 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS5_0` | CR.MAMP1 | 5 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS6_0` | CR.MAMP1 | 6 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS6_0` | CR.MAMP1 | 6 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS7_0` | CR.MAMP1 | 7 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS7_0` | CR.MAMP1 | 7 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS8_0` | CR.MAMP1 | 8 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS8_0` | CR.MAMP1 | 8 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS9_0` | CR.MAMP1 | 9 | inherited |  |
| Amplitude | `DAC_LFSRUNMASK_BITS9_0` | CR.MAMP1 | 9 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_1` | CR.MAMP1 | 0 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_1` | CR.MAMP1 | 0 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_1023` | CR.MAMP1 | 9 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_1023` | CR.MAMP1 | 9 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_127` | CR.MAMP1 | 6 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_127` | CR.MAMP1 | 6 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_15` | CR.MAMP1 | 3 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_15` | CR.MAMP1 | 3 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_2047` | CR.MAMP1 | 10 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_2047` | CR.MAMP1 | 10 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_255` | CR.MAMP1 | 7 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_255` | CR.MAMP1 | 7 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_3` | CR.MAMP1 | 1 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_3` | CR.MAMP1 | 1 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_31` | CR.MAMP1 | 4 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_31` | CR.MAMP1 | 4 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_4095` | CR.MAMP1 | 11 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_4095` | CR.MAMP1 | 11 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_511` | CR.MAMP1 | 8 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_511` | CR.MAMP1 | 8 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_63` | CR.MAMP1 | 5 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_63` | CR.MAMP1 | 5 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_7` | CR.MAMP1 | 2 | inherited |  |
| Amplitude | `DAC_TRIANGLEAMPLITUDE_7` | CR.MAMP1 | 2 | inherited |  |
| DAC_ConnectOnChipPeripheral | `DAC_CHIPCONNECT_INTERNAL_DISABLE` | OC.DAC_INTER1_CR | 0 | inherited |  |
| DAC_ConnectOnChipPeripheral | `DAC_CHIPCONNECT_INTERNAL_ENABLE` | OC.DAC_INTER1_CR | 1 | inherited |  |
| DAC_OutputMode | `DAC_OUTPUT_DISABLE` | OC.DAC_EXTEN | 0 | inherited | External output disable |
| DAC_OutputMode | `DAC_OUTPUT_ENABLE_BUFFER_DISABLE` | OC.DAC_EXTEN | 2 | inherited | External output enable without buffer |
| DAC_OutputMode | `DAC_OUTPUT_ENABLE_BUFFER_ENABLE` | OC.DAC_EXTEN | 1 | inherited | External output enable with buffer |
| DAC_OutputSelect | `DAC_OUTPUTSELECT_VOUT1_EXT` | OC.DAC_EXTCH_CR | 1 | inherited | External output VOUT1 |
| DAC_OutputSelect | `DAC_OUTPUTSELECT_VOUT2_EXT` | OC.DAC_EXTCH_CR | 2 | inherited | External output VOUT2 |
| DAC_OutputSelect | `DAC_OUTPUTSELECT_VOUT_EXT` | OC.DAC_EXTCH_CR | 0 | inherited | External output VOUT |
| DAC_Trigger | `DAC_TRIGGER_NONE` | CR.TEN1 | 0 | inherited | conversion is automatic once the DAC_DHRxxxx regis |
| DAC_Trigger | `DAC_TRIGGER_SOFTWARE` | CR.TEN1 | 1 | inherited | conversion started by software trigger for DAC cha |
| DAC_Trigger2 | `DAC_TRIGGER_NONE` | CR.TEN1 | 0 | inherited | conversion is automatic once the DAC_DHRxxxx regis |
| DAC_Trigger2 | `DAC_TRIGGER_SOFTWARE` | CR.TEN1 | 1 | inherited | conversion started by software trigger for DAC cha |
| DAC_VrefSelect | `DAC_VREFSELECT_VCC` | OC.DAC_VREFSEL | 0 | inherited | Select VCC |
| DAC_VrefSelect | `DAC_VREFSELECT_VREFBUF` | OC.DAC_VREFSEL | 1 | inherited | Select VREFBUF |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Data | 0..65520 | 待定 | IS_DAC_DATA |
| ResetData | 0..4095 | 待定 | IS_DAC_RESET_DATA |
| StepData | 0..65535 | 待定 | IS_DAC_STEP_DATA |
| value | 0..4095 | 待定 | IS_DAC_RAMPDELAY_DATA |
| HoldTime | 0..7 | 待定 | IS_DAC_CLK |
| HighTime | 0..7 | 待定 | IS_DAC_CLK |
| SetupTime | 0..7 | 待定 | IS_DAC_CLK |
| Data1 | 0..65520 | 待定 | IS_DAC_DATA |
| Data2 | 0..65520 | 待定 | IS_DAC_DATA |
| Data | 0..65520 | 待定 | IS_DAC_DATA |
| ResetData | 0..4095 | 待定 | IS_DAC_RESET_DATA |
| StepData | 0..65535 | 待定 | IS_DAC_STEP_DATA |
| value | 0..4095 | 待定 | IS_DAC_RAMPDELAY_DATA |
| HoldTime | 0..7 | 待定 | IS_DAC_CLK |
| HighTime | 0..7 | 待定 | IS_DAC_CLK |
| SetupTime | 0..7 | 待定 | IS_DAC_CLK |
| Data1 | 0..65520 | 待定 | IS_DAC_DATA |
| Data2 | 0..65520 | 待定 | IS_DAC_DATA |
| Alignment | 0..4095 | DHR12R1.DACC1DHR | llm_inferred |
| Alignment | 0..4095 | DHR12L1.DACC1DHR | llm_inferred |
| Alignment | 0..255 | DHR8R1.DACC1DHR | llm_inferred |
| Alignment | 0..4095 | DHR12R2.DACC2DHR | llm_inferred |
| Alignment | 0..4095 | DHR12L2.DACC2DHR | llm_inferred |
| Alignment | 0..255 | DHR8R2.DACC2DHR | llm_inferred |

## DMA

置信度计数:direct=2, inherited=27, llm_inferred=3

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| ArbMode | `DMA_ARB_FAST` | CCR.M2MARB | 0 | inherited | Do not release the bus after 1 data transfer |
| ArbMode | `DMA_ARB_POLL` | CCR.M2MARB | 1 | inherited | Release bus after 1 data transfer |
| BTCSuspend | `DMA_BTC_SUSPEND_DISABLE` | CCR.BTCSUSP | 0 | inherited | Disable suspend transfer after block transfer comp |
| BTCSuspend | `DMA_BTC_SUSPEND_ENABLE` | CCR.BTCSUSP | 1 | inherited | Enable suspend transfer after block transfer compl |
| MemDataAlignment | `DMA_MDATAALIGN_BYTE` | CCR.MSIZE | 0 | inherited | Memory data alignment : Byte |
| MemDataAlignment | `DMA_MDATAALIGN_HALFWORD` | CCR.MSIZE | 1 | inherited | Memory data alignment : HalfWord |
| MemDataAlignment | `DMA_MDATAALIGN_WORD` | CCR.MSIZE | 2 | inherited | Memory data alignment : Word |
| MemInc | `DMA_MADDR_DEC` | CCR.MINC | 2 | inherited | Memory address decrement |
| MemInc | `DMA_MADDR_FIX` | CCR.MINC | 0 | inherited | Memory address fixed |
| MemInc | `DMA_MADDR_INC` | CCR.MINC | 1 | inherited | Memory address increment |
| MemReload | `DMA_MRELOAD_DISABLE` | CCR.MNORLD | 1 | inherited | Memory address reload disable |
| MemReload | `DMA_MRELOAD_ENABLE` | CCR.MNORLD | 0 | inherited | Peripheral address reload enable |
| Mode | `DMA_FINITE_CIRCULAR` | CCR.CIRC | 1 | llm_inferred |  |
| Mode | `DMA_INFINITE_CIRCULAR` | CCR.CIRC | 1 | llm_inferred |  |
| Mode | `DMA_NORMAL` | CCR.CIRC | 0 | llm_inferred |  |
| PeriphDataAlignment | `DMA_PDATAALIGN_BYTE` | CCR.PSIZE | 0 | inherited | Peripheral data alignment : Byte |
| PeriphDataAlignment | `DMA_PDATAALIGN_HALFWORD` | CCR.PSIZE | 1 | inherited | Peripheral data alignment : HalfWord |
| PeriphDataAlignment | `DMA_PDATAALIGN_WORD` | CCR.PSIZE | 2 | inherited | Peripheral data alignment : Word |
| PeriphInc | `DMA_PADDR_DEC` | CCR.PINC | 2 | inherited | Peripheral address decrement |
| PeriphInc | `DMA_PADDR_FIX` | CCR.PINC | 0 | inherited | Peripheral address fixed |
| PeriphInc | `DMA_PADDR_INC` | CCR.PINC | 1 | inherited | Peripheral address increment |
| PeriphReload | `DMA_PRELOAD_DISABLE` | CCR.PNORLD | 1 | inherited | Peripheral address reload disable |
| PeriphReload | `DMA_PRELOAD_ENABLE` | CCR.PNORLD | 0 | inherited | Peripheral address reload enable |
| Priority | `DMA_PRIORITY_0` | CCR.PL | 0 | inherited | Priority level : 0 |
| Priority | `DMA_PRIORITY_1` | CCR.PL | 1 | inherited | Priority level : 1 |
| Priority | `DMA_PRIORITY_2` | CCR.PL | 2 | inherited | Priority level : 2 |
| Priority | `DMA_PRIORITY_3` | CCR.PL | 3 | inherited | Priority level : 3 |
| Priority | `DMA_PRIORITY_4` | CCR.PL | 4 | inherited | Priority level : 4 |
| TransMode | `DMA_TRANSFER_BULK` | CCR.TRANST | 1 | inherited | bulk transfer |
| TransMode | `DMA_TRANSFER_SINGLE` | CCR.TRANST | 0 | inherited | single transfer |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| BlockLen | 0..65535 | 待定 | IS_DMA_BLOCK_SIZE |

## EXTI

置信度计数:llm_inferred=6

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| GPIOSel | `EXTI_GPIOA` | EXTICR1.EXTI0 | 0 | llm_inferred |  |
| GPIOSel | `EXTI_GPIOB` | EXTICR1.EXTI1 | 1 | llm_inferred |  |
| GPIOSel | `EXTI_GPIOC` | EXTICR1.EXTI2 | 2 | llm_inferred |  |
| GPIOSel | `EXTI_GPIOD` | EXTICR1.EXTI3 | 3 | llm_inferred |  |
| Mode | `EXTI_MODE_EVENT` | EMR.EMR0 | 1 | llm_inferred |  |
| Mode | `EXTI_MODE_INTERRUPT` | IMR.IMR0 | 1 | llm_inferred |  |

## FDCAN

置信度计数:c_placement=16, inherited=4, llm_inferred=29

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| BufferIndex | `FDCAN_TX_BUFFER0` | TXBRP.TRP0 | 1 | llm_inferred |  |
| BufferIndex | `FDCAN_TX_BUFFER1` | TXBRP.TRP1 | 1 | llm_inferred |  |
| BufferIndex | `FDCAN_TX_BUFFER2` | TXBRP.TRP2 | 1 | llm_inferred |  |
| FIFO | `FDCAN_CFG_RX_FIFO0` | IE.RF0WE | 1 | llm_inferred |  |
| FIFO | `FDCAN_CFG_RX_FIFO1` | IE.RF1WE | 1 | llm_inferred |  |
| FrameFormat | `FDCAN_FRAME_CLASSIC` | CCCR.FDOE | 0 | inherited | Classic mode |
| FrameFormat | `FDCAN_FRAME_FD_NO_BRS` | CCCR.FDOE | 1 | inherited | FD mode without BitRate Switching |
| InterruptLine | `FDCAN_INTERRUPT_LINE0` | ILS.RF0NL | 0 | llm_inferred |  |
| InterruptLine | `FDCAN_INTERRUPT_LINE1` | ILS.RF0NL | 1 | llm_inferred |  |
| NonMatchingStd | `FDCAN_ACCEPT_IN_RX_FIFO1` | GFC.ANFS | 1 | llm_inferred |  |
| NonMatchingStd | `FDCAN_REJECT` | GFC.ANFS | 2 | llm_inferred |  |
| RejectRemoteStd | `FDCAN_REJECT_REMOTE` | GFC.RRFS | 1 | llm_inferred |  |
| RxBufferSize | `FDCAN_DATA_BYTES_12` | RXESC.RBDS | 5 | c_placement | 12 bytes data field |
| RxBufferSize | `FDCAN_DATA_BYTES_16` | RXESC.RBDS | 6 | c_placement | 16 bytes data field |
| RxBufferSize | `FDCAN_DATA_BYTES_20` | RXESC.RBDS | 7 | c_placement | 20 bytes data field |
| RxBufferSize | `FDCAN_DATA_BYTES_8` | RXESC.RBDS | 4 | c_placement | 8 bytes data field |
| RxFifo0ElmtSize | `FDCAN_DATA_BYTES_12` | RXESC.F0DS | 5 | c_placement | 12 bytes data field |
| RxFifo0ElmtSize | `FDCAN_DATA_BYTES_16` | RXESC.F0DS | 6 | c_placement | 16 bytes data field |
| RxFifo0ElmtSize | `FDCAN_DATA_BYTES_20` | RXESC.F0DS | 7 | c_placement | 20 bytes data field |
| RxFifo0ElmtSize | `FDCAN_DATA_BYTES_8` | RXESC.F0DS | 4 | c_placement | 8 bytes data field |
| RxFifo1ElmtSize | `FDCAN_DATA_BYTES_12` | RXESC.F1DS | 5 | c_placement | 12 bytes data field |
| RxFifo1ElmtSize | `FDCAN_DATA_BYTES_16` | RXESC.F1DS | 6 | c_placement | 16 bytes data field |
| RxFifo1ElmtSize | `FDCAN_DATA_BYTES_20` | RXESC.F1DS | 7 | c_placement | 20 bytes data field |
| RxFifo1ElmtSize | `FDCAN_DATA_BYTES_8` | RXESC.F1DS | 4 | c_placement | 8 bytes data field |
| TimeoutOperation | `FDCAN_TIMEOUT_RX_FIFO0` | TOCC.TOS | 2 | llm_inferred |  |
| TimeoutOperation | `FDCAN_TIMEOUT_RX_FIFO1` | TOCC.TOS | 3 | llm_inferred |  |
| TimeoutOperation | `FDCAN_TIMEOUT_TX_EVENT_FIFO` | TOCC.TOS | 1 | llm_inferred |  |
| TimestampOperation | `FDCAN_TIMESTAMP_INTERNAL` | TSCC.TSS | 1 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_10` | TSCC.TCP | 9 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_11` | TSCC.TCP | 10 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_12` | TSCC.TCP | 11 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_13` | TSCC.TCP | 12 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_14` | TSCC.TCP | 13 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_15` | TSCC.TCP | 14 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_16` | TSCC.TCP | 15 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_2` | TSCC.TCP | 1 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_3` | TSCC.TCP | 2 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_4` | TSCC.TCP | 3 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_5` | TSCC.TCP | 4 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_6` | TSCC.TCP | 5 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_7` | TSCC.TCP | 6 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_8` | TSCC.TCP | 7 | llm_inferred |  |
| TimestampPrescaler | `FDCAN_TIMESTAMP_PRESC_9` | TSCC.TCP | 8 | llm_inferred |  |
| TxElmtSize | `FDCAN_DATA_BYTES_12` | TXESC.TBDS | 5 | c_placement | 12 bytes data field |
| TxElmtSize | `FDCAN_DATA_BYTES_16` | TXESC.TBDS | 6 | c_placement | 16 bytes data field |
| TxElmtSize | `FDCAN_DATA_BYTES_20` | TXESC.TBDS | 7 | c_placement | 20 bytes data field |
| TxElmtSize | `FDCAN_DATA_BYTES_8` | TXESC.TBDS | 4 | c_placement | 8 bytes data field |
| TxFifoQueueMode | `FDCAN_TX_FIFO_OPERATION` | TXBC.TFQM | 0 | inherited | FIFO mode |
| TxFifoQueueMode | `FDCAN_TX_QUEUE_OPERATION` | TXBC.TFQM | 1 | inherited | Queue mode |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| NominalPrescaler | 1..512 | NBTP.(整寄存器) | IS_FDCAN_NOMINAL_PRESCALER |
| NominalSyncJumpWidth | 1..128 | NBTP.(整寄存器) | IS_FDCAN_NOMINAL_SJW |
| NominalTimeSeg1 | 1..256 | NBTP.(整寄存器) | IS_FDCAN_NOMINAL_TSEG1 |
| NominalTimeSeg2 | 1..128 | NBTP.(整寄存器) | IS_FDCAN_NOMINAL_TSEG2 |
| DataPrescaler | 1..32 | DBTP.(整寄存器) | IS_FDCAN_DATA_PRESCALER |
| DataSyncJumpWidth | 1..16 | DBTP.(整寄存器) | IS_FDCAN_DATA_SJW |
| DataTimeSeg1 | 1..32 | DBTP.(整寄存器) | IS_FDCAN_DATA_TSEG1 |
| DataTimeSeg2 | 1..16 | DBTP.(整寄存器) | IS_FDCAN_DATA_TSEG2 |
| AutoRetransmission | 0..1 | 待定 | FunctionalState |
| TransmitPause | 0..1 | 待定 | FunctionalState |
| ProtocolException | 0..1 | 待定 | FunctionalState |
| StdFiltersNbr | 0..255 | SIDFC.LSS | 扫描 |
| ExtFiltersNbr | 0..127 | XIDFC.LSE | 扫描 |
| RxFifo0ElmtsNbr | 0..127 | RXF0C.F0S | 扫描 |
| RxFifo1ElmtsNbr | 0..127 | RXF1C.F1S | 扫描 |
| TxEventsNbr | 0..63 | TXEFC.EFS | 扫描 |
| TxBuffersNbr | 0..63 | TXBC.NDTB | 扫描 |
| TxFifoQueueElmtsNbr | 0..63 | TXBC.TFQS | 扫描 |
| MessageRAMOffset | 0..16383 | SIDFC.FLSSA | llm_inferred |
| MessageRAMOffset | 0..16383 | XIDFC.FLESA | llm_inferred |
| RxBuffersNbr | 0..16383 | TXEFC.EFSA | llm_inferred |
| RxBuffersNbr | 0..16383 | TXBC.TBSA | llm_inferred |
| NonMatchingExt | 0..3 | GFC.ANFE | llm_inferred |
| RejectRemoteExt | 0..1 | GFC.RRFE | llm_inferred |
| RxFifo | 0..1 | RXF0C.F0OM | llm_inferred |
| RxFifo | 0..1 | RXF1C.F1OM | llm_inferred |
| RxBufferIndex | 0..1 | NDAT1.ND0 | llm_inferred |
| RxFifo | 0..127 | RXF0S.F0FL | llm_inferred |
| RxFifo | 0..127 | RXF1S.F1FL | llm_inferred |

## FLASH

置信度计数:direct=20, inherited=6, llm_inferred=88

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| BFBStart | `OB_BFB_START_BANK0` | OPTBFB.BFB | 0 | inherited |  |
| BFBStart | `OB_BFB_START_BANK1` | OPTBFB.BFB | 1 | inherited |  |
| Banks | `FLASH_BANK_0` | CR.MER | 1 | llm_inferred |  |
| Banks | `FLASH_BANK_0` | CR.MER | 1 | llm_inferred |  |
| Banks | `FLASH_BANK_1` | CR.MER | 1 | llm_inferred |  |
| Banks | `FLASH_BANK_1` | CR.MER | 1 | llm_inferred |  |
| Banks | `FLASH_BANK_MSK` | CR.MER | 1 | llm_inferred |  |
| BootEntryPoint | `OB_BOOT_LOCK_DISABLE` | OPTR1.BOOT_LOCK | 0 | inherited | Boot Lock Disable |
| BootEntryPoint | `OB_BOOT_LOCK_ENABLE` | OPTR1.BOOT_LOCK | 1 | inherited | Boot Lock Enable |
| RDPLevel | `OB_RDP_LEVEL_0` | OPTR1.RDP | 170 | llm_inferred |  |
| RDPLevel | `OB_RDP_LEVEL_1` | OPTR1.RDP | 85 | llm_inferred |  |
| RDPLevel | `OB_RDP_LEVEL_2` | OPTR1.RDP | 204 | llm_inferred |  |
| USERConfig | `OB_WWDG_HW` | OPTR1.WWDG_SW | 0 | inherited | Hardware window watchdog |
| USERConfig | `OB_WWDG_SW` | OPTR1.WWDG_SW | 1 | inherited | Software window watchdog |
| WRPSector | `FLASH_WRPR_WRP_0` | WRPR0.BANK0_WRPR | 1 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_1` | WRPR0.BANK0_WRPR | 2 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_10` | WRPR0.BANK0_WRPR | 1024 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_11` | WRPR0.BANK0_WRPR | 2048 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_12` | WRPR0.BANK0_WRPR | 4096 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_13` | WRPR0.BANK0_WRPR | 8192 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_14` | WRPR0.BANK0_WRPR | 16384 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_15` | WRPR0.BANK0_WRPR | 32768 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_2` | WRPR0.BANK0_WRPR | 4 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_3` | WRPR0.BANK0_WRPR | 8 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_4` | WRPR0.BANK0_WRPR | 16 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_5` | WRPR0.BANK0_WRPR | 32 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_6` | WRPR0.BANK0_WRPR | 64 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_7` | WRPR0.BANK0_WRPR | 128 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_8` | WRPR0.BANK0_WRPR | 256 | llm_inferred |  |
| WRPSector | `FLASH_WRPR_WRP_9` | WRPR0.BANK0_WRPR | 512 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages0to31` | WRPR0.BANK0_WRPR | 1 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages128to159` | WRPR0.BANK0_WRPR | 16 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages160to191` | WRPR0.BANK0_WRPR | 32 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages192to223` | WRPR0.BANK0_WRPR | 64 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages224to255` | WRPR0.BANK0_WRPR | 128 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages256to287` | WRPR0.BANK0_WRPR | 256 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages288to319` | WRPR0.BANK0_WRPR | 512 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages320to351` | WRPR0.BANK0_WRPR | 1024 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages32to63` | WRPR0.BANK0_WRPR | 2 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages352to383` | WRPR0.BANK0_WRPR | 2048 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages384to415` | WRPR0.BANK0_WRPR | 4096 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages416to447` | WRPR0.BANK0_WRPR | 8192 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages448to479` | WRPR0.BANK0_WRPR | 16384 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages480to511` | WRPR0.BANK0_WRPR | 32768 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages64to95` | WRPR0.BANK0_WRPR | 4 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_Pages96to127` | WRPR0.BANK0_WRPR | 8 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_0` | WRPR0.BANK0_WRPR | 1 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_1` | WRPR0.BANK0_WRPR | 2 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_10` | WRPR0.BANK0_WRPR | 1024 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_11` | WRPR0.BANK0_WRPR | 2048 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_12` | WRPR0.BANK0_WRPR | 4096 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_13` | WRPR0.BANK0_WRPR | 8192 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_14` | WRPR0.BANK0_WRPR | 16384 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_15` | WRPR0.BANK0_WRPR | 32768 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_2` | WRPR0.BANK0_WRPR | 4 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_3` | WRPR0.BANK0_WRPR | 8 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_4` | WRPR0.BANK0_WRPR | 16 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_5` | WRPR0.BANK0_WRPR | 32 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_6` | WRPR0.BANK0_WRPR | 64 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_7` | WRPR0.BANK0_WRPR | 128 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_8` | WRPR0.BANK0_WRPR | 256 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK0_SECTOR_9` | WRPR0.BANK0_WRPR | 512 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages0to31` | WRPR1.BANK1_WRPR | 1 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages128to159` | WRPR1.BANK1_WRPR | 16 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages160to191` | WRPR1.BANK1_WRPR | 32 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages192to223` | WRPR1.BANK1_WRPR | 64 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages224to255` | WRPR1.BANK1_WRPR | 128 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages256to287` | WRPR1.BANK1_WRPR | 256 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages288to319` | WRPR1.BANK1_WRPR | 512 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages320to351` | WRPR1.BANK1_WRPR | 1024 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages32to63` | WRPR1.BANK1_WRPR | 2 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages352to383` | WRPR1.BANK1_WRPR | 2048 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages384to415` | WRPR1.BANK1_WRPR | 4096 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages416to447` | WRPR1.BANK1_WRPR | 8192 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages448to479` | WRPR1.BANK1_WRPR | 16384 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages480to511` | WRPR1.BANK1_WRPR | 32768 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages64to95` | WRPR1.BANK1_WRPR | 4 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_Pages96to127` | WRPR1.BANK1_WRPR | 8 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_0` | WRPR1.BANK1_WRPR | 1 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_1` | WRPR1.BANK1_WRPR | 2 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_10` | WRPR1.BANK1_WRPR | 1024 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_11` | WRPR1.BANK1_WRPR | 2048 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_12` | WRPR1.BANK1_WRPR | 4096 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_13` | WRPR1.BANK1_WRPR | 8192 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_14` | WRPR1.BANK1_WRPR | 16384 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_15` | WRPR1.BANK1_WRPR | 32768 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_2` | WRPR1.BANK1_WRPR | 4 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_3` | WRPR1.BANK1_WRPR | 8 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_4` | WRPR1.BANK1_WRPR | 16 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_5` | WRPR1.BANK1_WRPR | 32 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_6` | WRPR1.BANK1_WRPR | 64 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_7` | WRPR1.BANK1_WRPR | 128 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_8` | WRPR1.BANK1_WRPR | 256 | llm_inferred |  |
| WRPSector | `OB_WRP_BANK1_SECTOR_9` | WRPR1.BANK1_WRPR | 512 | llm_inferred |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| PCROPStartAddr | 0..511 | PCROPR0.PCROP0SR | llm_inferred |
| PCROPStartAddr | 0..511 | PCROPR1.PCROP1SR | llm_inferred |
| PCROPEndAddr | 0..511 | PCROPR0.PCROP0ER | llm_inferred |
| PCROPEndAddr | 0..511 | PCROPR1.PCROP1ER | llm_inferred |
| SECConfig | 0..1 | CR.SECPROT0 | llm_inferred |
| SECConfig | 0..1 | CR.SECPROT1 | llm_inferred |
| SecSize | 0..511 | SECR0.SEC_SIZEER0 | llm_inferred |
| SecSize | 0..511 | SECR1.SEC_SIZEER1 | llm_inferred |
| PCROPConfig | 0..511 | PCROPR0.PCROP0SR | llm_inferred |
| PCROPConfig | 0..511 | PCROPR0.PCROP0ER | llm_inferred |
| PCROPConfig | 0..511 | PCROPR1.PCROP1SR | llm_inferred |
| PCROPConfig | 0..511 | PCROPR1.PCROP1ER | llm_inferred |
| RDPLevel | 0..255 | OPTR1.RDP | llm_inferred |

## GPIO

置信度计数:c_placement=23

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| Mode | `GPIO_MODE_AF_OD` | MODER.MODE0 | 2 | c_placement | Alternate Function Open Drain Mode |
| Mode | `GPIO_MODE_AF_OD` | OTYPER.OT0 | 1 | c_placement | Alternate Function Open Drain Mode |
| Mode | `GPIO_MODE_AF_PP` | MODER.MODE0 | 2 | c_placement | Alternate Function Push Pull Mode |
| Mode | `GPIO_MODE_AF_PP` | OTYPER.OT0 | 0 | c_placement | Alternate Function Push Pull Mode |
| Mode | `GPIO_MODE_ANALOG` | MODER.MODE0 | 3 | c_placement | Analog Mode |
| Mode | `GPIO_MODE_EVT_FALLING` | MODER.MODE0 | 0 | c_placement | External Event Mode with Falling edge trigger dete |
| Mode | `GPIO_MODE_EVT_RISING` | MODER.MODE0 | 0 | c_placement | External Event Mode with Rising edge trigger detec |
| Mode | `GPIO_MODE_EVT_RISING_FALLING` | MODER.MODE0 | 0 | c_placement | External Event Mode with Rising/Falling edge trigg |
| Mode | `GPIO_MODE_INPUT` | MODER.MODE0 | 0 | c_placement | Input Floating Mode |
| Mode | `GPIO_MODE_IT_FALLING` | MODER.MODE0 | 0 | c_placement | External Interrupt Mode with Falling edge trigger  |
| Mode | `GPIO_MODE_IT_RISING` | MODER.MODE0 | 0 | c_placement | External Interrupt Mode with Rising edge trigger d |
| Mode | `GPIO_MODE_IT_RISING_FALLING` | MODER.MODE0 | 0 | c_placement | External Interrupt Mode with Rising/Falling edge t |
| Mode | `GPIO_MODE_OUTPUT_OD` | MODER.MODE0 | 1 | c_placement | Output Open Drain Mode |
| Mode | `GPIO_MODE_OUTPUT_OD` | OTYPER.OT0 | 1 | c_placement | Output Open Drain Mode |
| Mode | `GPIO_MODE_OUTPUT_PP` | MODER.MODE0 | 1 | c_placement | Output Push Pull Mode |
| Mode | `GPIO_MODE_OUTPUT_PP` | OTYPER.OT0 | 0 | c_placement | Output Push Pull Mode |
| Pull | `GPIO_NOPULL` | PUPDR.PUPD0 | 0 | c_placement | No Pull-up or Pull-down activation |
| Pull | `GPIO_PULLDOWN` | PUPDR.PUPD0 | 2 | c_placement | Pull-down activation |
| Pull | `GPIO_PULLUP` | PUPDR.PUPD0 | 1 | c_placement | Pull-up activation |
| Speed | `GPIO_SPEED_FREQ_HIGH` | OSPEEDR.OSPEED0 | 2 | c_placement | High speed |
| Speed | `GPIO_SPEED_FREQ_LOW` | OSPEEDR.OSPEED0 | 0 | c_placement | Low speed |
| Speed | `GPIO_SPEED_FREQ_MEDIUM` | OSPEEDR.OSPEED0 | 1 | c_placement | Medium speed |
| Speed | `GPIO_SPEED_FREQ_VERY_HIGH` | OSPEEDR.OSPEED0 | 3 | c_placement | Very high speed |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Alternate | 0..15 | AFRL.AFSEL0 | 扫描 |
| Alternate | 0..15 | AFRH.AFSEL8 | 扫描 |

## I2C

置信度计数:inherited=30

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| AddressingMode | `I2C_ADDRESSINGMODE_10BIT` | OAR1.ADDMODE | 1 | inherited |  |
| AddressingMode | `I2C_ADDRESSINGMODE_7BIT` | OAR1.ADDMODE | 0 | inherited |  |
| DataHoldTimeSel | `I2C_DATA_HOLD_TIME_HARDWARE` | TRISE.THOLDDATA_SEL | 0 | inherited |  |
| DataHoldTimeSel | `I2C_DATA_HOLD_TIME_SOFTWARE` | TRISE.THOLDDATA_SEL | 1 | inherited |  |
| DualAddressMode | `I2C_DUALADDRESS_DISABLE` | OAR2.ENDUAL | 0 | inherited |  |
| DualAddressMode | `I2C_DUALADDRESS_ENABLE` | OAR2.ENDUAL | 1 | inherited |  |
| DutyCycle | `I2C_DUTYCYCLE_16_9` | CCR.DUTY | 1 | inherited |  |
| DutyCycle | `I2C_DUTYCYCLE_2` | CCR.DUTY | 0 | inherited |  |
| GeneralCallMode | `I2C_GENERALCALL_DISABLE` | CR1.ENGC | 0 | inherited |  |
| GeneralCallMode | `I2C_GENERALCALL_ENABLE` | CR1.ENGC | 1 | inherited |  |
| NoStretchMode | `I2C_NOSTRETCH_DISABLE` | CR1.NOSTRETCH | 0 | inherited |  |
| NoStretchMode | `I2C_NOSTRETCH_ENABLE` | CR1.NOSTRETCH | 1 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK01` | OAR2.OA2MSK | 1 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK02` | OAR2.OA2MSK | 2 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK03` | OAR2.OA2MSK | 3 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK04` | OAR2.OA2MSK | 4 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK05` | OAR2.OA2MSK | 5 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK06` | OAR2.OA2MSK | 6 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_MASK07` | OAR2.OA2MSK | 7 | inherited |  |
| OwnAddress2Masks | `I2C_OA2_NOMASK` | OAR2.OA2MSK | 0 | inherited |  |
| ToutCnt | `I2C_WAKEUP_TIMEOUT_CNT_128` | CR1.WKUP_CNT | 3 | inherited |  |
| ToutCnt | `I2C_WAKEUP_TIMEOUT_CNT_2` | CR1.WKUP_CNT | 0 | inherited |  |
| ToutCnt | `I2C_WAKEUP_TIMEOUT_CNT_32` | CR1.WKUP_CNT | 2 | inherited |  |
| ToutCnt | `I2C_WAKEUP_TIMEOUT_CNT_8` | CR1.WKUP_CNT | 1 | inherited |  |
| ToutDiv | `I2C_WAKEUP_TIMEOUT_CLK_DIV_1024` | CR1.WKUP_DIV | 3 | inherited |  |
| ToutDiv | `I2C_WAKEUP_TIMEOUT_CLK_DIV_128` | CR1.WKUP_DIV | 0 | inherited |  |
| ToutDiv | `I2C_WAKEUP_TIMEOUT_CLK_DIV_256` | CR1.WKUP_DIV | 1 | inherited |  |
| ToutDiv | `I2C_WAKEUP_TIMEOUT_CLK_DIV_512` | CR1.WKUP_DIV | 2 | inherited |  |
| TripleAddressMode | `I2C_TRIPLEADDRESS_DISABLE` | OAR3.ENTRIPLE | 0 | inherited |  |
| TripleAddressMode | `I2C_TRIPLEADDRESS_ENABLE` | OAR3.ENTRIPLE | 1 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| ClockSpeed | 0..1600000 | 待定 | IS_I2C_CLOCK_SPEED |
| OwnAddress1 | 自由值 | OAR1.(整寄存器) | 扫描 |
| OwnAddress2 | 自由值 | OAR2.(整寄存器) | 扫描 |
| OwnAddress3 | 自由值 | OAR3.(整寄存器) | 扫描 |

## IRDA

置信度计数:llm_inferred=1

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| IrDAMode | `IRDA_POWERMODE_NORMAL` | CR3.IRLP | 0 | llm_inferred |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Prescaler | 0..255 | GTPR.PSC | llm_inferred |
| BaudRate | 0..4095 | BRR.DIV_MAN | llm_inferred |
| BaudRate | 0..15 | BRR.DIV_FRA | llm_inferred |

## IWDG

置信度计数:inherited=7

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| Prescaler | `IWDG_PRESCALER_128` | PR.PR | 5 | inherited | IWDG prescaler set to 128 |
| Prescaler | `IWDG_PRESCALER_16` | PR.PR | 2 | inherited | IWDG prescaler set to 16 |
| Prescaler | `IWDG_PRESCALER_256` | PR.PR | 6 | inherited | IWDG prescaler set to 256 |
| Prescaler | `IWDG_PRESCALER_32` | PR.PR | 3 | inherited | IWDG prescaler set to 32 |
| Prescaler | `IWDG_PRESCALER_4` | PR.PR | 0 | inherited | IWDG prescaler set to 4 |
| Prescaler | `IWDG_PRESCALER_64` | PR.PR | 4 | inherited | IWDG prescaler set to 64 |
| Prescaler | `IWDG_PRESCALER_8` | PR.PR | 1 | inherited | IWDG prescaler set to 8 |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Reload | 自由值 | RLR.(整寄存器) | 扫描 |

## LPTIM

置信度计数:direct=2, inherited=33

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| Input1Source | `LPTIM_INPUT1SOURCE_COMP1` | OR.IN1 | 1 | inherited |  |
| Input1Source | `LPTIM_INPUT1SOURCE_GPIO` | OR.IN1 | 0 | inherited |  |
| OutputPolarity | `LPTIM_OUTPUTPOLARITY_HIGH` | CFGR.WAVPOL | 0 | inherited |  |
| OutputPolarity | `LPTIM_OUTPUTPOLARITY_LOW` | CFGR.WAVPOL | 1 | inherited |  |
| Polarity | `LPTIM_CLOCKPOLARITY_FALLING` | CFGR.CKPOL | 1 | inherited |  |
| Polarity | `LPTIM_CLOCKPOLARITY_RISING` | CFGR.CKPOL | 0 | inherited |  |
| Polarity | `LPTIM_CLOCKPOLARITY_RISING_FALLING` | CFGR.CKPOL | 2 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV1` | CFGR.PRESC | 0 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV128` | CFGR.PRESC | 7 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV16` | CFGR.PRESC | 4 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV2` | CFGR.PRESC | 1 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV32` | CFGR.PRESC | 5 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV4` | CFGR.PRESC | 2 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV64` | CFGR.PRESC | 6 | inherited |  |
| Prescaler | `LPTIM_PRESCALER_DIV8` | CFGR.PRESC | 3 | inherited |  |
| SampleTime | `LPTIM_CLOCKSAMPLETIME_2TRANSITIONS` | CFGR.CKFLT | 1 | inherited |  |
| SampleTime | `LPTIM_CLOCKSAMPLETIME_4TRANSITIONS` | CFGR.CKFLT | 2 | inherited |  |
| SampleTime | `LPTIM_CLOCKSAMPLETIME_8TRANSITIONS` | CFGR.CKFLT | 3 | inherited |  |
| SampleTime | `LPTIM_CLOCKSAMPLETIME_DIRECTTRANSITION` | CFGR.CKFLT | 0 | inherited |  |
| SampleTime | `LPTIM_TRIGSAMPLETIME_2TRANSITIONS` | CFGR.TRGFLT | 1 | inherited |  |
| SampleTime | `LPTIM_TRIGSAMPLETIME_4TRANSITIONS` | CFGR.TRGFLT | 2 | inherited |  |
| SampleTime | `LPTIM_TRIGSAMPLETIME_8TRANSITIONS` | CFGR.TRGFLT | 3 | inherited |  |
| SampleTime | `LPTIM_TRIGSAMPLETIME_DIRECTTRANSITION` | CFGR.TRGFLT | 0 | inherited |  |
| Source | `LPTIM_CLOCKSOURCE_APBCLOCK_LPOSC` | CFGR.CKSEL | 0 | inherited |  |
| Source | `LPTIM_CLOCKSOURCE_ULPTIM` | CFGR.CKSEL | 1 | inherited |  |
| Source | `LPTIM_TRIGSOURCE_0` | CFGR.TRIGSEL | 0 | inherited | GPIO |
| Source | `LPTIM_TRIGSOURCE_1` | CFGR.TRIGSEL | 1 | inherited | RTC_ALARM |
| Source | `LPTIM_TRIGSOURCE_2` | CFGR.TRIGSEL | 2 | inherited | COMP1 OUT |
| Source | `LPTIM_TRIGSOURCE_3` | CFGR.TRIGSEL | 3 | inherited | COMP2 OUT |
| Source | `LPTIM_TRIGSOURCE_4` | CFGR.TRIGSEL | 4 | inherited | COMP3 OUT |
| Source | `LPTIM_TRIGSOURCE_5` | CFGR.TRIGSEL | 5 | inherited | COMP4 OUT |
| UpdateMode | `LPTIM_UPDATE_ENDOFPERIOD` | CFGR.PRELOAD | 1 | inherited |  |
| UpdateMode | `LPTIM_UPDATE_IMMEDIATE` | CFGR.PRELOAD | 0 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Timeout | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Timeout | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Pulse | 0..65535 | 待定 | IS_LPTIM_PULSE |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |
| Period | 0..65535 | 待定 | IS_LPTIM_PERIOD |

## LPUART

置信度计数:c_placement=12, direct=6, inherited=29

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| AddressLength | `LPUART_ADDRESS_DETECT_4B` | CR2.ADDM7 | 0 | inherited |  |
| AddressLength | `LPUART_ADDRESS_DETECT_7B` | CR2.ADDM7 | 1 | inherited |  |
| ClockPrescaler | `LPUART_PRESCALER_DIV1` | PRESC.PRESCALER | 0 | c_placement | fclk_pres = fclk |
| ClockPrescaler | `LPUART_PRESCALER_DIV10` | PRESC.PRESCALER | 5 | c_placement | fclk_pres = fclk/10 |
| ClockPrescaler | `LPUART_PRESCALER_DIV12` | PRESC.PRESCALER | 6 | c_placement | fclk_pres = fclk/12 |
| ClockPrescaler | `LPUART_PRESCALER_DIV128` | PRESC.PRESCALER | 10 | c_placement | fclk_pres = fclk/128 |
| ClockPrescaler | `LPUART_PRESCALER_DIV16` | PRESC.PRESCALER | 7 | c_placement | fclk_pres = fclk/16 |
| ClockPrescaler | `LPUART_PRESCALER_DIV2` | PRESC.PRESCALER | 1 | c_placement | fclk_pres = fclk/2 |
| ClockPrescaler | `LPUART_PRESCALER_DIV256` | PRESC.PRESCALER | 11 | c_placement | fclk_pres = fclk/256 |
| ClockPrescaler | `LPUART_PRESCALER_DIV32` | PRESC.PRESCALER | 8 | c_placement | fclk_pres = fclk/32 |
| ClockPrescaler | `LPUART_PRESCALER_DIV4` | PRESC.PRESCALER | 2 | c_placement | fclk_pres = fclk/4 |
| ClockPrescaler | `LPUART_PRESCALER_DIV6` | PRESC.PRESCALER | 3 | c_placement | fclk_pres = fclk/6 |
| ClockPrescaler | `LPUART_PRESCALER_DIV64` | PRESC.PRESCALER | 9 | c_placement | fclk_pres = fclk/64 |
| ClockPrescaler | `LPUART_PRESCALER_DIV8` | PRESC.PRESCALER | 4 | c_placement | fclk_pres = fclk/8 |
| DMADisableonRxError | `LPUART_ADVFEATURE_DMA_DISABLEONRXERROR` | CR3.DDRE | 1 | inherited | DMA disable on Reception Error |
| DMADisableonRxError | `LPUART_ADVFEATURE_DMA_ENABLEONRXERROR` | CR3.DDRE | 0 | inherited | DMA enable on Reception Error |
| DataInvert | `LPUART_ADVFEATURE_DATAINV_DISABLE` | CR2.DATAINV | 0 | inherited | Binary data inversion disable |
| DataInvert | `LPUART_ADVFEATURE_DATAINV_ENABLE` | CR2.DATAINV | 1 | inherited | Binary data inversion enable |
| MSBFirst | `LPUART_ADVFEATURE_MSBFIRST_DISABLE` | CR2.MSBFIRST | 0 | inherited | Most significant bit sent/received first disable |
| MSBFirst | `LPUART_ADVFEATURE_MSBFIRST_ENABLE` | CR2.MSBFIRST | 1 | inherited | Most significant bit sent/received first enable |
| OverrunDisable | `LPUART_ADVFEATURE_OVERRUN_DISABLE` | CR3.OVRDIS | 1 | inherited | RX overrun disable |
| OverrunDisable | `LPUART_ADVFEATURE_OVERRUN_ENABLE` | CR3.OVRDIS | 0 | inherited | RX overrun enable |
| Parity | `LPUART_PARITY_EVEN` | CR1.PCE | 1 | inherited | Even parity |
| Parity | `LPUART_PARITY_NONE` | CR1.PCE | 0 | inherited | No parity |
| Polarity | `LPUART_DE_POLARITY_HIGH` | CR3.DEP | 0 | inherited |  |
| Polarity | `LPUART_DE_POLARITY_LOW` | CR3.DEP | 1 | inherited |  |
| RxPinLevelInvert | `LPUART_ADVFEATURE_RXINV_DISABLE` | CR2.RXINV | 0 | inherited | RX pin active level inversion disable |
| RxPinLevelInvert | `LPUART_ADVFEATURE_RXINV_ENABLE` | CR2.RXINV | 1 | inherited | RX pin active level inversion enable |
| StopBits | `LPUART_STOPBITS_1` | CR2.STOP | 0 | inherited | LPUART frame with 1 stop bit |
| StopBits | `LPUART_STOPBITS_2` | CR2.STOP | 2 | inherited | LPUART frame with 2 stop bits |
| Swap | `LPUART_ADVFEATURE_SWAP_DISABLE` | CR2.SWAP | 0 | inherited | TX/RX pins swap disable |
| Swap | `LPUART_ADVFEATURE_SWAP_ENABLE` | CR2.SWAP | 1 | inherited | TX/RX pins swap enable |
| TxPinLevelInvert | `LPUART_ADVFEATURE_TXINV_DISABLE` | CR2.TXINV | 0 | inherited | TX pin active level inversion disable |
| TxPinLevelInvert | `LPUART_ADVFEATURE_TXINV_ENABLE` | CR2.TXINV | 1 | inherited | TX pin active level inversion enable |
| TxoeAlway | `LPUART_ADVFEATURE_TXOEALWAYSON_DISABLE` | CR2.TXOE_ALWAYS_ON | 0 | inherited | LPUART output control by hardware |
| TxoeAlway | `LPUART_ADVFEATURE_TXOEALWAYSON_ENABLE` | CR2.TXOE_ALWAYS_ON | 1 | inherited | LPUART output control by software |
| WakeUpEvent | `LPUART_WAKEUP_ON_ADDRESS` | CR3.WUS | 0 | inherited | LPUART wake-up on address |
| WakeUpEvent | `LPUART_WAKEUP_ON_READDATA_NONEMPTY` | CR3.WUS | 3 | inherited | LPUART wake-up on receive data register not empty |
| WakeUpEvent | `LPUART_WAKEUP_ON_STARTBIT` | CR3.WUS | 2 | inherited | LPUART wake-up on start bit |
| WakeUpMethod | `LPUART_WAKEUPMETHOD_ADDRESSMARK` | CR1.WAKE | 1 | inherited |  |
| WakeUpMethod | `LPUART_WAKEUPMETHOD_IDLELINE` | CR1.WAKE | 0 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| AssertionTime | 0..31 | 待定 | IS_LPUART_ASSERTIONTIME |
| DeassertionTime | 0..31 | 待定 | IS_LPUART_DEASSERTIONTIME |
| AssertionTime | 0..31 | 待定 | IS_LPUART_ASSERTIONTIME |
| DeassertionTime | 0..31 | 待定 | IS_LPUART_DEASSERTIONTIME |
| BaudRate | 0..1048575 | BRR.BBR | llm_inferred |
| AddressLength | 0..1 | CR2.ADDM7 | llm_inferred |
| Address | 0..255 | CR2.ADD | llm_inferred |

## OPA

置信度计数:inherited=37

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| CommonModeVoltage | `OPA_COMMONMODEVOLTAGE_BUILDIN` | CSR.VBSEL | 1 | inherited | The common mode voltage is set to be the built-in  |
| CommonModeVoltage | `OPA_COMMONMODEVOLTAGE_EXTERNAL` | CSR.VBSEL | 0 | inherited | The common mode voltage is set to be the external  |
| InvertingInput | `OPA_INVERTINGINPUT_IO0` | CSR.VNSEL | 0 | inherited | Inverting input connected to I/O VINM0 (PC3 for OP |
| InvertingInput | `OPA_INVERTINGINPUT_IO1` | CSR.VNSEL | 1 | inherited | Inverting input connected to I/0 VINM1 or OPA1_VIN |
| InvertingInput | `OPA_INVERTINGINPUT_IO2` | CSR.VNSEL | 2 | inherited | Inverting input connected to OPA1_VINN1 (None for  |
| Mode | `OPA_FOLLOWER_MODE` | CSR.MODE | 2 | inherited | follower mode |
| Mode | `OPA_PGA_MODE` | CSR.MODE | 1 | inherited | PGA mode |
| Mode | `OPA_STANDALONE_MODE` | CSR.MODE | 0 | inherited | standalone mode |
| NonInvertingInput | `OPA_NONINVERTINGINPUT_IO0` | CSR.VPSEL | 0 | inherited | Non inverting input connected to I/O VINP0 (PC2 fo |
| NonInvertingInput | `OPA_NONINVERTINGINPUT_IO1` | CSR.VPSEL | 1 | inherited | Non inverting input connected to I/O VINP1 (PC0 fo |
| PgaConnect | `OPA_PGA_CONNECT_INVERTINGINPUT_IO0_BIAS` | CSR.PGA_GAIN | 8 | inherited | In PGA mode, the inverting input is connected to V |
| PgaConnect | `OPA_PGA_CONNECT_INVERTINGINPUT_NO` | CSR.PGA_GAIN | 0 | inherited | In PGA mode, the inverting input is not connected |
| PgaGain | `OPA_PGA_GAIN_12_OR_MINUS_11` | CSR.PGA_GAIN | 3 | inherited | PGA gain could be 12 or -11 |
| PgaGain | `OPA_PGA_GAIN_16_OR_MINUS_15` | CSR.PGA_GAIN | 4 | inherited | PGA gain could be 16 or -15 |
| PgaGain | `OPA_PGA_GAIN_24_OR_MINUS_23` | CSR.PGA_GAIN | 5 | inherited | PGA gain could be 24 or -23 |
| PgaGain | `OPA_PGA_GAIN_2_OR_MINUS_1` | CSR.PGA_GAIN | 0 | inherited | PGA gain could be 2 or -1 |
| PgaGain | `OPA_PGA_GAIN_32_OR_MINUS_31` | CSR.PGA_GAIN | 6 | inherited | PGA gain could be 32 or -31 |
| PgaGain | `OPA_PGA_GAIN_4_OR_MINUS_3` | CSR.PGA_GAIN | 1 | inherited | PGA gain could be 4 or -3 |
| PgaGain | `OPA_PGA_GAIN_8_OR_MINUS_7` | CSR.PGA_GAIN | 2 | inherited | PGA gain could be 8 or -7 |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV1` | CSR.VBIAS | 0 | inherited | The bias voltage is set to be the div1 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV10` | CSR.VBIAS | 9 | inherited | The bias voltage is set to be the div10 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV11` | CSR.VBIAS | 10 | inherited | The bias voltage is set to be the div11 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV12` | CSR.VBIAS | 11 | inherited | The bias voltage is set to be the div12 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV13` | CSR.VBIAS | 12 | inherited | The bias voltage is set to be the div13 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV14` | CSR.VBIAS | 13 | inherited | The bias voltage is set to be the div14 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV15` | CSR.VBIAS | 14 | inherited | The bias voltage is set to be the div15 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV16` | CSR.VBIAS | 15 | inherited | The bias voltage is set to be the div16 of VCC/VRE |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV2` | CSR.VBIAS | 1 | inherited | The bias voltage is set to be the div2 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV3` | CSR.VBIAS | 2 | inherited | The bias voltage is set to be the div3 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV4` | CSR.VBIAS | 3 | inherited | The bias voltage is set to be the div4 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV5` | CSR.VBIAS | 4 | inherited | The bias voltage is set to be the div5 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV6` | CSR.VBIAS | 5 | inherited | The bias voltage is set to be the div6 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV7` | CSR.VBIAS | 6 | inherited | The bias voltage is set to be the div7 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV8` | CSR.VBIAS | 7 | inherited | The bias voltage is set to be the div8 of VCC/VREF |
| VoltageBias | `OPA_VOLTAGEBIAS_DIV9` | CSR.VBIAS | 8 | inherited | The bias voltage is set to be the div9 of VCC/VREF |
| VoltageRefer | `OPA_VOLTAGEREFER_VCC` | CSR.VREF_SEL | 0 | inherited | The reference voltage is set to be the VCC |
| VoltageRefer | `OPA_VOLTAGEREFER_VREFBUF` | CSR.VREF_SEL | 1 | inherited | The reference voltage is set to be the VREFBUF |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| InternalOutput | 0..1 | 待定 | FunctionalState |
| ExternalOutput | 0..1 | 待定 | FunctionalState |

## PWR

置信度计数:direct=7, inherited=6, llm_inferred=2

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| PVDFilter | `PWR_PVD_FILTER_1CLOCK` | CR2.FLTEN | 1 | inherited |  |
| PVDFilter | `PWR_PVD_FILTER_NONE` | CR2.FLTEN | 0 | inherited |  |
| Regulator | `PWR_LOWPOWERREGULATOR_ON` | CR1.VR_MODE_SLP | 1 | inherited |  |
| Regulator | `PWR_LOWPOWERREGULATOR_ON` | CR1.VR_MODE_SLP | 1 | inherited |  |
| Regulator | `PWR_MAINREGULATOR_ON` | CR1.VR_MODE_SLP | 0 | inherited |  |
| Regulator | `PWR_MAINREGULATOR_ON` | CR1.VR_MODE_SLP | 0 | inherited |  |
| STOPEntry | `PWR_STOPENTRY_WFE` | CR1.LPMS_SLP | 1 | llm_inferred |  |
| STOPEntry | `PWR_STOPENTRY_WFI` | CR1.LPMS_ACTIVE | 1 | llm_inferred |  |

## RCC

置信度计数:inherited=117, llm_inferred=2

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| AHBCLKDivider | `RCC_SYSCLK_DIV1` | CFGR1.HPRE | 0 | inherited | SYSCLK not divided |
| AHBCLKDivider | `RCC_SYSCLK_DIV128` | CFGR1.HPRE | 13 | inherited | SYSCLK divided by 128 |
| AHBCLKDivider | `RCC_SYSCLK_DIV16` | CFGR1.HPRE | 11 | inherited | SYSCLK divided by 16 |
| AHBCLKDivider | `RCC_SYSCLK_DIV2` | CFGR1.HPRE | 8 | inherited | SYSCLK divided by 2 |
| AHBCLKDivider | `RCC_SYSCLK_DIV256` | CFGR1.HPRE | 14 | inherited | SYSCLK divided by 256 |
| AHBCLKDivider | `RCC_SYSCLK_DIV4` | CFGR1.HPRE | 9 | inherited | SYSCLK divided by 4 |
| AHBCLKDivider | `RCC_SYSCLK_DIV512` | CFGR1.HPRE | 15 | inherited | SYSCLK divided by 512 |
| AHBCLKDivider | `RCC_SYSCLK_DIV64` | CFGR1.HPRE | 12 | inherited | SYSCLK divided by 64 |
| AHBCLKDivider | `RCC_SYSCLK_DIV8` | CFGR1.HPRE | 10 | inherited | SYSCLK divided by 8 |
| APB1CLKDivider | `RCC_HCLK_DIV1` | CFGR1.PPRE1 | 0 | inherited | HCLK divided by 1 |
| APB1CLKDivider | `RCC_HCLK_DIV16` | CFGR1.PPRE1 | 7 | inherited | HCLK divided by 16 |
| APB1CLKDivider | `RCC_HCLK_DIV2` | CFGR1.PPRE1 | 4 | inherited | HCLK divided by 2 |
| APB1CLKDivider | `RCC_HCLK_DIV4` | CFGR1.PPRE1 | 5 | inherited | HCLK divided by 4 |
| APB1CLKDivider | `RCC_HCLK_DIV8` | CFGR1.PPRE1 | 6 | inherited | HCLK divided by 8 |
| APB2CLKDivider | `RCC_HCLK_DIV1` | CFGR1.PPRE1 | 0 | inherited | HCLK divided by 1 |
| APB2CLKDivider | `RCC_HCLK_DIV16` | CFGR1.PPRE1 | 7 | inherited | HCLK divided by 16 |
| APB2CLKDivider | `RCC_HCLK_DIV2` | CFGR1.PPRE1 | 4 | inherited | HCLK divided by 2 |
| APB2CLKDivider | `RCC_HCLK_DIV4` | CFGR1.PPRE1 | 5 | inherited | HCLK divided by 4 |
| APB2CLKDivider | `RCC_HCLK_DIV8` | CFGR1.PPRE1 | 6 | inherited | HCLK divided by 8 |
| AdcClockSelection | `RCC_ADCCLKSOURCE_HSE` | CCIPR2.ADC12SEL | 3 | inherited |  |
| AdcClockSelection | `RCC_ADCCLKSOURCE_HSI` | CCIPR2.ADC12SEL | 2 | inherited |  |
| AdcClockSelection | `RCC_ADCCLKSOURCE_PLL` | CCIPR2.ADC12SEL | 1 | inherited |  |
| AdcClockSelection | `RCC_ADCCLKSOURCE_SYSCLK` | CCIPR2.ADC12SEL | 0 | inherited |  |
| Comp1ClockSelection | `RCC_COMP1CLKSOURCE_LSE` | CCIPR1.COMP1SEL | 2 | inherited |  |
| Comp1ClockSelection | `RCC_COMP1CLKSOURCE_LSI` | CCIPR1.COMP1SEL | 1 | inherited |  |
| Comp1ClockSelection | `RCC_COMP1CLKSOURCE_PCLK2` | CCIPR1.COMP1SEL | 0 | inherited |  |
| Comp2ClockSelection | `RCC_COMP2CLKSOURCE_LSE` | CCIPR1.COMP2SEL | 2 | inherited |  |
| Comp2ClockSelection | `RCC_COMP2CLKSOURCE_LSI` | CCIPR1.COMP2SEL | 1 | inherited |  |
| Comp2ClockSelection | `RCC_COMP2CLKSOURCE_PCLK2` | CCIPR1.COMP2SEL | 0 | inherited |  |
| Comp3ClockSelection | `RCC_COMP3CLKSOURCE_LSE` | CCIPR1.COMP3SEL | 2 | inherited |  |
| Comp3ClockSelection | `RCC_COMP3CLKSOURCE_LSI` | CCIPR1.COMP3SEL | 1 | inherited |  |
| Comp3ClockSelection | `RCC_COMP3CLKSOURCE_PCLK2` | CCIPR1.COMP3SEL | 0 | inherited |  |
| Comp4ClockSelection | `RCC_COMP4CLKSOURCE_LSE` | CCIPR1.COMP4SEL | 2 | inherited |  |
| Comp4ClockSelection | `RCC_COMP4CLKSOURCE_LSI` | CCIPR1.COMP4SEL | 1 | inherited |  |
| Comp4ClockSelection | `RCC_COMP4CLKSOURCE_PCLK2` | CCIPR1.COMP4SEL | 0 | inherited |  |
| FdcanClockSelection | `RCC_FDCANCLKSOURCE_HSE` | CCIPR2.FDCANCKSEL | 2 | inherited |  |
| FdcanClockSelection | `RCC_FDCANCLKSOURCE_PCLK1` | CCIPR2.FDCANCKSEL | 1 | inherited |  |
| FdcanClockSelection | `RCC_FDCANCLKSOURCE_PLL` | CCIPR2.FDCANCKSEL | 0 | inherited |  |
| HSEFreq | `RCC_HSE_16_24MHz` | ECSCR.HSE_DRV | 1 | inherited | HSE hign drive capability |
| HSEFreq | `RCC_HSE_24_32MHz` | ECSCR.HSE_DRV | 1 | inherited | HSE very high drive capability |
| HSEFreq | `RCC_HSE_4_8MHz` | ECSCR.HSE_DRV | 0 | inherited | HSE low drive capability |
| HSEFreq | `RCC_HSE_8_16MHz` | ECSCR.HSE_DRV | 1 | inherited | HSE medium drive capability |
| HSEState | `RCC_HSE_OFF` | CR.HSEON | 0 | inherited | HSE clock deactivation |
| HSEState | `RCC_HSE_ON` | CR.HSEON | 1 | inherited | HSE clock activation |
| HSIDiv | `RCC_HSI_DIV1` | CR.HSIDIV | 0 | inherited | HSI clock is not divided |
| HSIDiv | `RCC_HSI_DIV2` | CR.HSIDIV | 1 | inherited | HSI clock is divided by 2 |
| HSIDiv | `RCC_HSI_DIV4` | CR.HSIDIV | 2 | inherited | HSI clock is divided by 4 |
| HSIDiv | `RCC_HSI_DIV8` | CR.HSIDIV | 3 | inherited | HSI clock is divided by 8 |
| HSIState | `RCC_HSI_OFF` | CR.HSION | 0 | inherited | HSI clock deactivation |
| HSIState | `RCC_HSI_ON` | CR.HSION | 1 | inherited | HSI clock activation |
| LSEDriver | `RCC_LSEDRIVE_HIGH` | BDCR.LSEDRV | 2 | inherited | LSE high drive capability |
| LSEDriver | `RCC_LSEDRIVE_LOW` | BDCR.LSEDRV | 0 | inherited | LSE low drive capability |
| LSEDriver | `RCC_LSEDRIVE_MEDIUM` | BDCR.LSEDRV | 1 | inherited | LSE medium drive capability |
| LSEDriver | `RCC_LSEDRIVE_VERY_HIGH` | BDCR.LSEDRV | 3 | inherited | LSE vrey high drive capability |
| LSEState | `RCC_LSE_OFF` | BDCR.LSEON | 0 | inherited | LSE clock deactivation |
| LSEState | `RCC_LSE_ON` | BDCR.LSEON | 1 | inherited | LSE clock activation |
| LSIState | `RCC_LSI_OFF` | BDCR.LSION | 0 | inherited | LSI clock deactivation |
| LSIState | `RCC_LSI_ON` | BDCR.LSION | 1 | inherited | LSI clock activation |
| LptimClockSelection | `RCC_LPTIMCLKSOURCE_HSI` | CCIPR2.LPTIMSEL | 2 | inherited |  |
| LptimClockSelection | `RCC_LPTIMCLKSOURCE_LSE` | CCIPR2.LPTIMSEL | 3 | inherited |  |
| LptimClockSelection | `RCC_LPTIMCLKSOURCE_LSI` | CCIPR2.LPTIMSEL | 1 | inherited |  |
| LptimClockSelection | `RCC_LPTIMCLKSOURCE_PCLK1` | CCIPR2.LPTIMSEL | 0 | inherited |  |
| LpuartClockSelection | `RCC_LPUARTCLKSOURCE_HSI` | CCIPR1.LPUARTSEL | 2 | inherited |  |
| LpuartClockSelection | `RCC_LPUARTCLKSOURCE_LSE` | CCIPR1.LPUARTSEL | 3 | inherited |  |
| LpuartClockSelection | `RCC_LPUARTCLKSOURCE_PCLK1` | CCIPR1.LPUARTSEL | 0 | inherited |  |
| LpuartClockSelection | `RCC_LPUARTCLKSOURCE_SYSCLK` | CCIPR1.LPUARTSEL | 1 | inherited |  |
| PLLMUL | `RCC_PLL_MUL10` | PLLCFGR1.PLLMUL | 8 | inherited |  |
| PLLMUL | `RCC_PLL_MUL11` | PLLCFGR1.PLLMUL | 9 | inherited |  |
| PLLMUL | `RCC_PLL_MUL12` | PLLCFGR1.PLLMUL | 10 | inherited |  |
| PLLMUL | `RCC_PLL_MUL13` | PLLCFGR1.PLLMUL | 11 | inherited |  |
| PLLMUL | `RCC_PLL_MUL14` | PLLCFGR1.PLLMUL | 12 | inherited |  |
| PLLMUL | `RCC_PLL_MUL15` | PLLCFGR1.PLLMUL | 13 | inherited |  |
| PLLMUL | `RCC_PLL_MUL16` | PLLCFGR1.PLLMUL | 14 | inherited |  |
| PLLMUL | `RCC_PLL_MUL2` | PLLCFGR1.PLLMUL | 0 | inherited |  |
| PLLMUL | `RCC_PLL_MUL3` | PLLCFGR1.PLLMUL | 1 | inherited |  |
| PLLMUL | `RCC_PLL_MUL4` | PLLCFGR1.PLLMUL | 2 | inherited |  |
| PLLMUL | `RCC_PLL_MUL5` | PLLCFGR1.PLLMUL | 3 | inherited |  |
| PLLMUL | `RCC_PLL_MUL6` | PLLCFGR1.PLLMUL | 4 | inherited |  |
| PLLMUL | `RCC_PLL_MUL7` | PLLCFGR1.PLLMUL | 5 | inherited |  |
| PLLMUL | `RCC_PLL_MUL8` | PLLCFGR1.PLLMUL | 6 | inherited |  |
| PLLMUL | `RCC_PLL_MUL9` | PLLCFGR1.PLLMUL | 7 | inherited |  |
| PLLSource | `RCC_PLLSOURCE_HSE` | PLLCFGR1.PLLSRC | 1 | inherited | HSE clock selected as PLL entry clock source |
| PLLSource | `RCC_PLLSOURCE_HSI` | PLLCFGR1.PLLSRC | 0 | inherited | HSI clock selected as PLL entry clock source |
| PLLState | `RCC_PLL_OFF` | CR.PLLON | 0 | llm_inferred |  |
| PLLState | `RCC_PLL_ON` | CR.PLLON | 1 | llm_inferred |  |
| PvdFilterClockSelection | `RCC_PVDFILTERCLK_LSE` | CCIPR1.PVDSEL | 1 | inherited |  |
| PvdFilterClockSelection | `RCC_PVDFILTERCLK_LSI` | CCIPR1.PVDSEL | 0 | inherited |  |
| PvdFilterClockSelection | `RCC_PVDFILTERCLK_PCLK1` | CCIPR1.PVDSEL | 2 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_1` | CFGR1.MCO1PRE | 0 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_128` | CFGR1.MCO1PRE | 14 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_16` | CFGR1.MCO1PRE | 11 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_2` | CFGR1.MCO1PRE | 8 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_256` | CFGR1.MCO1PRE | 15 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_32` | CFGR1.MCO1PRE | 12 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_4` | CFGR1.MCO1PRE | 9 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_64` | CFGR1.MCO1PRE | 13 | inherited |  |
| RCC_MCODiv | `RCC_MCODIV_8` | CFGR1.MCO1PRE | 10 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_HCLK` | CFGR1.MCO1SEL | 10 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_HSE` | CFGR1.MCO1SEL | 3 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_HSI` | CFGR1.MCO1SEL | 2 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_HSI10M` | CFGR1.MCO1SEL | 9 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_LSE` | CFGR1.MCO1SEL | 6 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_LSI` | CFGR1.MCO1SEL | 5 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_NOCLOCK` | CFGR1.MCO1SEL | 0 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_PCLK1` | CFGR1.MCO1SEL | 11 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_PCLK2` | CFGR1.MCO1SEL | 12 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_PLLCLK` | CFGR1.MCO1SEL | 4 | inherited |  |
| RCC_MCOSource | `RCC_MCOSOURCE_SYSCLK` | CFGR1.MCO1SEL | 1 | inherited |  |
| RtcClockSelection | `RCC_RTCCLKSOURCE_HSE_DIV32` | BDCR.RTCSEL | 3 | inherited | HSE oscillator clock divided by 32 used as RTC clo |
| RtcClockSelection | `RCC_RTCCLKSOURCE_LSE` | BDCR.RTCSEL | 1 | inherited | LSE oscillator clock used as RTC clock |
| RtcClockSelection | `RCC_RTCCLKSOURCE_LSI` | BDCR.RTCSEL | 2 | inherited | LSI oscillator clock used as RTC clock |
| RtcClockSelection | `RCC_RTCCLKSOURCE_NONE` | BDCR.RTCSEL | 0 | inherited | No clock |
| SYSCLKSource | `RCC_SYSCLKSOURCE_HSE` | CFGR1.SW | 1 | inherited | HSE selected as system clock |
| SYSCLKSource | `RCC_SYSCLKSOURCE_HSISYS` | CFGR1.SW | 0 | inherited | HSISYS selected as system clock |
| SYSCLKSource | `RCC_SYSCLKSOURCE_PLLCLK` | CFGR1.SW | 2 | inherited | PLL selected as system clock |
| UsartClockSelection | `RCC_USARTCLKSOURCE_HSI` | CCIPR1.USARTSEL | 2 | inherited |  |
| UsartClockSelection | `RCC_USARTCLKSOURCE_LSE` | CCIPR1.USARTSEL | 3 | inherited |  |
| UsartClockSelection | `RCC_USARTCLKSOURCE_PCLK2` | CCIPR1.USARTSEL | 0 | inherited |  |
| UsartClockSelection | `RCC_USARTCLKSOURCE_SYSCLK` | CCIPR1.USARTSEL | 1 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| HSICalibrationValue | 0..3 | ICSCR.HSI_FS | manual |
| HSICalibrationValue | 0..65535 | ICSCR.HSI_TRIMCR | manual |
| AdcPLLDiv | 0..3 | CCIPR3.PLL_ADC_DIV | llm_inferred |
| FdcanPLLDiv | 0..15 | CCIPR3.PLL_FDCAN_DIV | llm_inferred |

## RTC

置信度计数:direct=3

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| SmouthCalibMinusPulsesValue | 0..127 | 待定 | IS_RTC_SMOOTH_CALIB_MINUS |
| SmouthCalibMinusPulsesValue | 0..127 | 待定 | IS_RTC_SMOOTH_CALIB_MINUS |
| AsynchPrediv | 0..15 | PRLH.PRL | llm_inferred |
| AsynchPrediv | 0..65535 | PRLL.PRL | llm_inferred |

## SCI

置信度计数:llm_inferred=10

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| AutoBaudRateEnable | `SCI_ADVFEATURE_AUTOBAUDRATE_DISABLE` | CR3.ABREN | 0 | llm_inferred |  |
| AutoBaudRateEnable | `SCI_ADVFEATURE_AUTOBAUDRATE_ENABLE` | CR3.ABREN | 1 | llm_inferred |  |
| AutoBaudRateMode | `SCI_ADVFEATURE_AUTOBAUDRATE_ONSTARTBIT` | CR3.ABRMOD | 0 | llm_inferred |  |
| DataInvert | `SCI_ADVFEATURE_DATAINV_DISABLE` | CR1.DATAINV | 0 | llm_inferred |  |
| MSBFirst | `SCI_ADVFEATURE_MSBFIRST_DISABLE` | CR1.MSB | 0 | llm_inferred |  |
| OverSampling | `SCI_OVERSAMPLING_16` | CR3.OVER8 | 0 | llm_inferred |  |
| RxPinLevelInvert | `SCI_ADVFEATURE_RXINV_DISABLE` | CR1.RX_INV | 0 | llm_inferred |  |
| StopBits | `SCI_STOPBITS_1` | CR2.STOP | 0 | llm_inferred |  |
| Swap | `SCI_ADVFEATURE_SWAP_DISABLE` | CR1.SWAP | 0 | llm_inferred |  |
| TxPinLevelInvert | `SCI_ADVFEATURE_TXINV_DISABLE` | CR1.TX_INV | 0 | llm_inferred |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Address | 0..255 | 待定 | IS_SCI_ADDRESS |
| TimeoutValue | 0..16777215 | 待定 | IS_SCI_RECEIVER_TIMEOUT_VALUE |
| AssertionTime | 0..31 | 待定 | IS_SCI_ASSERTIONTIME |
| DeassertionTime | 0..31 | 待定 | IS_SCI_DEASSERTIONTIME |
| BaudRate | 0..4500000 | 待定 | IS_SCI_BAUDRATE |
| Address | 0..255 | 待定 | IS_SCI_ADDRESS |
| Address | 0..255 | 待定 | IS_SCI_ADDRESS |
| TimeoutValue | 0..16777215 | 待定 | IS_SCI_RECEIVER_TIMEOUT_VALUE |
| AssertionTime | 0..31 | 待定 | IS_SCI_ASSERTIONTIME |
| DeassertionTime | 0..31 | 待定 | IS_SCI_DEASSERTIONTIME |
| Mode | 0..1 | CR1.RE | llm_inferred |
| Mode | 0..1 | CR1.TE | llm_inferred |
| AddressLength | 0..1 | CR1.ADDM7 | llm_inferred |
| BreakDetectLength | 0..1 | CR2.LBDL | llm_inferred |
| WakeUpMethod | 0..1 | CR1.WAKE | llm_inferred |
| Polarity | 0..1 | CR2.DEP | llm_inferred |
| Threshold | 0..7 | CR1.TXFTCFG | llm_inferred |
| Threshold | 0..7 | CR1.RXFTCFG | llm_inferred |

## SMARTCARD

置信度计数:llm_inferred=11

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| CLKLastBit | `SMARTCARD_LASTBIT_DISABLE` | CR2.LBCL | 0 | llm_inferred |  |
| CLKPhase | `SMARTCARD_PHASE_1EDGE` | CR2.CPHA | 0 | llm_inferred |  |
| CLKPolarity | `SMARTCARD_POLARITY_LOW` | CR2.CPOL | 0 | llm_inferred |  |
| DataInvert | `SMARTCARD_ADVFEATURE_DATAINV_DISABLE` | CR1.DATAINV | 0 | llm_inferred |  |
| MSBFirst | `SMARTCARD_ADVFEATURE_MSBFIRST_DISABLE` | CR1.MSB | 0 | llm_inferred |  |
| NACKEnable | `SMARTCARD_NACK_DISABLE` | CR3.NACK | 0 | llm_inferred |  |
| NACKEnable | `SMARTCARD_NACK_ENABLE` | CR3.NACK | 1 | llm_inferred |  |
| RxPinLevelInvert | `SMARTCARD_ADVFEATURE_RXINV_DISABLE` | CR1.RX_INV | 0 | llm_inferred |  |
| Swap | `SMARTCARD_ADVFEATURE_SWAP_DISABLE` | CR1.SWAP | 0 | llm_inferred |  |
| TimeOutEnable | `SMARTCARD_TIMEOUT_DISABLE` | CR2.RTOEN | 0 | llm_inferred |  |
| TxPinLevelInvert | `SMARTCARD_ADVFEATURE_TXINV_DISABLE` | CR1.TX_INV | 0 | llm_inferred |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| TimeOutValue | 0..16777215 | 待定 | IS_SMARTCARD_TIMEOUT_VALUE |
| AutoRetryCount | 0..7 | 待定 | IS_SMARTCARD_AUTORETRY_COUNT |
| WordLength | 0..1 | CR1.M0 | llm_inferred |
| WordLength | 0..1 | CR1.M1 | llm_inferred |
| StopBits | 0..3 | CR2.STOP | llm_inferred |
| Parity | 0..1 | CR1.PS | llm_inferred |
| Parity | 0..1 | CR1.PCE | llm_inferred |
| Mode | 0..1 | CR1.TE | llm_inferred |
| Mode | 0..1 | CR1.RE | llm_inferred |
| Prescaler | 0..255 | GTPR.PSC | llm_inferred |
| GuardTime | 0..255 | GTPR.GT | llm_inferred |
| BlockLength | 0..255 | RTOR.BLEN | llm_inferred |
| TxCompletionIndication | 0..1 | CR1.TCIE | llm_inferred |
| BaudRate | 0..15 | BRR.DIV_FRA | llm_inferred |
| BaudRate | 0..4095 | BRR.DIV_MAN | llm_inferred |
| Threshold | 0..7 | CR1.TXFTCFG | llm_inferred |
| Threshold | 0..7 | CR1.RXFTCFG | llm_inferred |

## SPI

置信度计数:direct=2, inherited=22, llm_inferred=5

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_128` | CR1.BR | 6 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_16` | CR1.BR | 3 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_2` | CR1.BR | 0 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_256` | CR1.BR | 7 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_32` | CR1.BR | 4 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_4` | CR1.BR | 1 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_64` | CR1.BR | 5 | inherited |  |
| BaudRatePrescaler | `SPI_BAUDRATEPRESCALER_8` | CR1.BR | 2 | inherited |  |
| CLKPhase | `SPI_PHASE_1EDGE` | CR1.CPHA | 0 | inherited |  |
| CLKPhase | `SPI_PHASE_2EDGE` | CR1.CPHA | 1 | inherited |  |
| CLKPolarity | `SPI_POLARITY_HIGH` | CR1.CPOL | 1 | inherited |  |
| CLKPolarity | `SPI_POLARITY_LOW` | CR1.CPOL | 0 | inherited |  |
| CRCCalculation | `SPI_CRCCALCULATION_DISABLE` | CR1.CRCEN | 0 | inherited |  |
| CRCCalculation | `SPI_CRCCALCULATION_ENABLE` | CR1.CRCEN | 1 | inherited |  |
| CRCLength | `SPI_CRC_LENGTH_16BIT` | CR1.DFF | 1 | llm_inferred |  |
| CRCLength | `SPI_CRC_LENGTH_8BIT` | CR1.DFF | 0 | llm_inferred |  |
| CRCLength | `SPI_CRC_LENGTH_DATASIZE` | CR1.DFF | 0 | llm_inferred |  |
| DataSize | `SPI_DATASIZE_16BIT` | CR1.DFF | 1 | llm_inferred |  |
| DataSize | `SPI_DATASIZE_8BIT` | CR1.DFF | 0 | llm_inferred |  |
| FirstBit | `SPI_FIRSTBIT_LSB` | CR1.LSBFIRST | 1 | inherited |  |
| FirstBit | `SPI_FIRSTBIT_MSB` | CR1.LSBFIRST | 0 | inherited |  |
| NSS | `SPI_NSS_HARD_INPUT` | CR1.SSM | 0 | inherited |  |
| NSS | `SPI_NSS_SOFT` | CR1.SSM | 1 | inherited |  |
| SampleSelect | `SPI_SAMPLESELECT_DISABLE` | CR2.SAMPLE_SELECT | 0 | inherited |  |
| SampleSelect | `SPI_SAMPLESELECT_ENABLE` | CR2.SAMPLE_SELECT | 1 | inherited |  |
| TIMode | `SPI_TIMODE_DISABLE` | CR2.FRF | 0 | inherited |  |
| TIMode | `SPI_TIMODE_ENABLE` | CR2.FRF | 1 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| CRCPolynomial | 1..65535 | CRCPR.(整寄存器) | IS_SPI_CRC_POLYNOMIAL |

## TIM

置信度计数:direct=73, inherited=134, llm_inferred=31

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| AutoReloadPreload | `TIM_AUTORELOAD_PRELOAD_DISABLE` | CR1.ARPE | 0 | inherited | TIMx_ARR register is not buffered |
| AutoReloadPreload | `TIM_AUTORELOAD_PRELOAD_ENABLE` | CR1.ARPE | 1 | inherited | TIMx_ARR register is buffered |
| BurstBaseAddress | `TIM_DMABASE_AF1` | DCR.DBA | 24 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_AF2` | DCR.DBA | 25 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_ARR` | DCR.DBA | 11 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_BDTR` | DCR.DBA | 17 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCER` | DCR.DBA | 8 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCMR1` | DCR.DBA | 6 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCMR2` | DCR.DBA | 7 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCMR3` | DCR.DBA | 20 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCR1` | DCR.DBA | 13 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCR2` | DCR.DBA | 14 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCR3` | DCR.DBA | 15 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCR4` | DCR.DBA | 16 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCR5` | DCR.DBA | 18 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CCR6` | DCR.DBA | 19 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CNT` | DCR.DBA | 9 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_CR2` | DCR.DBA | 1 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_DIER` | DCR.DBA | 3 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_DTR2` | DCR.DBA | 21 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_ECR` | DCR.DBA | 22 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_EGR` | DCR.DBA | 5 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_MTADCCR` | DCR.DBA | 27 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_PSC` | DCR.DBA | 10 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_RCR` | DCR.DBA | 12 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_SMCR` | DCR.DBA | 2 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_SR` | DCR.DBA | 4 | llm_inferred |  |
| BurstBaseAddress | `TIM_DMABASE_TISEL` | DCR.DBA | 23 | llm_inferred |  |
| ClearInputPolarity | `TIM_CLEARINPUTPOLARITY_INVERTED` | SMCR.ETP | 1 | inherited | Polarity for ETRx pin |
| ClearInputPolarity | `TIM_CLEARINPUTPOLARITY_NONINVERTED` | SMCR.ETP | 0 | inherited | Polarity for ETRx pin |
| ClearInputPrescaler | `TIM_CLEARINPUTPRESCALER_DIV1` | SMCR.ETPS | 0 | inherited |  |
| ClearInputPrescaler | `TIM_CLEARINPUTPRESCALER_DIV2` | SMCR.ETPS | 1 | inherited |  |
| ClearInputPrescaler | `TIM_CLEARINPUTPRESCALER_DIV4` | SMCR.ETPS | 2 | inherited |  |
| ClearInputPrescaler | `TIM_CLEARINPUTPRESCALER_DIV8` | SMCR.ETPS | 3 | inherited |  |
| ClearInputSource | `TIM_CLEARINPUTSOURCE_COMP1` | AF2.OCRSEL | 0 | inherited | OCREF_CLR_INT is connected to COMP1 output |
| ClearInputSource | `TIM_CLEARINPUTSOURCE_COMP2` | AF2.OCRSEL | 1 | inherited | OCREF_CLR_INT is connected to COMP2 output |
| ClearInputSource | `TIM_CLEARINPUTSOURCE_COMP3` | AF2.OCRSEL | 2 | inherited | OCREF_CLR_INT is connected to COMP3 output |
| ClearInputSource | `TIM_CLEARINPUTSOURCE_COMP4` | AF2.OCRSEL | 3 | inherited | OCREF_CLR_INT is connected to COMP4 output |
| ClearInputSource | `TIM_CLEARINPUTSOURCE_ETR` | AF2.OCRSEL | 1 | inherited | OCREF_CLR is connected to ETRF input |
| ClockDivision | `TIM_CLOCKDIVISION_DIV1` | CR1.CKD | 0 | inherited | Clock division: tDTS=tCK_INT |
| ClockDivision | `TIM_CLOCKDIVISION_DIV2` | CR1.CKD | 1 | inherited | Clock division: tDTS=2*tCK_INT |
| ClockDivision | `TIM_CLOCKDIVISION_DIV4` | CR1.CKD | 2 | inherited | Clock division: tDTS=4*tCK_INT |
| ClockPrescaler | `TIM_CLOCKPRESCALER_DIV1` | SMCR.ETPS | 0 | inherited | No prescaler is used |
| ClockPrescaler | `TIM_CLOCKPRESCALER_DIV2` | SMCR.ETPS | 1 | inherited | Prescaler for External ETR Clock: Capture performe |
| ClockPrescaler | `TIM_CLOCKPRESCALER_DIV4` | SMCR.ETPS | 2 | inherited | Prescaler for External ETR Clock: Capture performe |
| ClockPrescaler | `TIM_CLOCKPRESCALER_DIV8` | SMCR.ETPS | 3 | inherited | Prescaler for External ETR Clock: Capture performe |
| Direction | `TIM_ENCODERINDEX_DIRECTION_DOWN` | ECR.IDIR | 2 | inherited |  |
| Direction | `TIM_ENCODERINDEX_DIRECTION_UP` | ECR.IDIR | 1 | inherited |  |
| Direction | `TIM_ENCODERINDEX_DIRECTION_UP_DOWN` | ECR.IDIR | 0 | inherited |  |
| IC1Polarity | `TIM_ENCODERINPUTPOLARITY_FALLING` | CCER.CC1P | 1 | inherited | Encoder input with falling edge polarity |
| IC1Polarity | `TIM_ENCODERINPUTPOLARITY_RISING` | CCER.CC1P | 0 | inherited | Encoder input with rising edge polarity |
| IC1Polarity | `TIM_ICPOLARITY_FALLING` | CCER.CC1P | 1 | inherited | Capture triggered by falling edge on timer input |
| IC1Polarity | `TIM_ICPOLARITY_RISING` | CCER.CC1P | 0 | inherited | Capture triggered by rising edge on timer input |
| IC2Polarity | `TIM_ENCODERINPUTPOLARITY_FALLING` | CCER.CC1P | 1 | inherited | Encoder input with falling edge polarity |
| IC2Polarity | `TIM_ENCODERINPUTPOLARITY_RISING` | CCER.CC1P | 0 | inherited | Encoder input with rising edge polarity |
| ICPolarity | `TIM_ICPOLARITY_FALLING` | CCER.CC1P | 1 | inherited | Capture triggered by falling edge on timer input |
| ICPolarity | `TIM_ICPOLARITY_FALLING` | CCER.CC1P | 1 | inherited | Capture triggered by falling edge on timer input |
| ICPolarity | `TIM_ICPOLARITY_RISING` | CCER.CC1P | 0 | inherited | Capture triggered by rising edge on timer input |
| ICPolarity | `TIM_ICPOLARITY_RISING` | CCER.CC1P | 0 | inherited | Capture triggered by rising edge on timer input |
| InputTrigger | `TIM_TS_ETRF` | SMCR.TS | 7 | inherited | Filtered External Trigger input (ETRF) |
| InputTrigger | `TIM_TS_ITR0` | SMCR.TS | 0 | inherited |  |
| InputTrigger | `TIM_TS_ITR0` | SMCR.TS | 0 | inherited |  |
| InputTrigger | `TIM_TS_ITR0` | SMCR.TS | 0 | inherited |  |
| InputTrigger | `TIM_TS_ITR0` | SMCR.TS | 0 | inherited | Internal Trigger 0 (ITR0) |
| InputTrigger | `TIM_TS_ITR1` | SMCR.TS | 1 | inherited |  |
| InputTrigger | `TIM_TS_ITR1` | SMCR.TS | 1 | inherited |  |
| InputTrigger | `TIM_TS_ITR1` | SMCR.TS | 1 | inherited |  |
| InputTrigger | `TIM_TS_ITR1` | SMCR.TS | 1 | inherited | Internal Trigger 1 (ITR1) |
| InputTrigger | `TIM_TS_ITR2` | SMCR.TS | 2 | inherited |  |
| InputTrigger | `TIM_TS_ITR2` | SMCR.TS | 2 | inherited |  |
| InputTrigger | `TIM_TS_ITR2` | SMCR.TS | 2 | inherited |  |
| InputTrigger | `TIM_TS_ITR2` | SMCR.TS | 2 | inherited | Internal Trigger 2 (ITR2) |
| InputTrigger | `TIM_TS_ITR3` | SMCR.TS | 3 | inherited |  |
| InputTrigger | `TIM_TS_ITR3` | SMCR.TS | 3 | inherited |  |
| InputTrigger | `TIM_TS_ITR3` | SMCR.TS | 3 | inherited |  |
| InputTrigger | `TIM_TS_ITR3` | SMCR.TS | 3 | inherited | Internal Trigger 3 (ITR3) |
| InputTrigger | `TIM_TS_ITR5` | SMCR.TS | 1 | inherited |  |
| InputTrigger | `TIM_TS_ITR5` | SMCR.TS | 1 | inherited |  |
| InputTrigger | `TIM_TS_ITR5` | SMCR.TS | 1 | inherited |  |
| InputTrigger | `TIM_TS_ITR5` | SMCR.TS | 1 | inherited | Internal Trigger 5 (ITR5) |
| InputTrigger | `TIM_TS_ITR6` | SMCR.TS | 2 | inherited |  |
| InputTrigger | `TIM_TS_ITR6` | SMCR.TS | 2 | inherited |  |
| InputTrigger | `TIM_TS_ITR6` | SMCR.TS | 2 | inherited |  |
| InputTrigger | `TIM_TS_ITR6` | SMCR.TS | 2 | inherited | Internal Trigger 6 (ITR6) |
| InputTrigger | `TIM_TS_ITR7` | SMCR.TS | 3 | inherited |  |
| InputTrigger | `TIM_TS_ITR7` | SMCR.TS | 3 | inherited |  |
| InputTrigger | `TIM_TS_ITR7` | SMCR.TS | 3 | inherited |  |
| InputTrigger | `TIM_TS_ITR7` | SMCR.TS | 3 | inherited | Internal Trigger 7 (ITR7) |
| InputTrigger | `TIM_TS_ITR8` | SMCR.TS | 4 | inherited |  |
| InputTrigger | `TIM_TS_ITR8` | SMCR.TS | 4 | inherited |  |
| InputTrigger | `TIM_TS_ITR8` | SMCR.TS | 4 | inherited |  |
| InputTrigger | `TIM_TS_ITR8` | SMCR.TS | 4 | inherited | Internal Trigger 8 (ITR8) |
| InputTrigger | `TIM_TS_ITR9` | SMCR.TS | 5 | inherited |  |
| InputTrigger | `TIM_TS_ITR9` | SMCR.TS | 5 | inherited |  |
| InputTrigger | `TIM_TS_ITR9` | SMCR.TS | 5 | inherited |  |
| InputTrigger | `TIM_TS_ITR9` | SMCR.TS | 5 | inherited | Internal Trigger 9 (ITR9) |
| InputTrigger | `TIM_TS_TI1FP1` | SMCR.TS | 5 | inherited | Filtered Timer Input 1 (TI1FP1) |
| InputTrigger | `TIM_TS_TI1F_ED` | SMCR.TS | 4 | inherited | TI1 Edge Detector (TI1F_ED) |
| InputTrigger | `TIM_TS_TI2FP2` | SMCR.TS | 6 | inherited | Filtered Timer Input 2 (TI2FP2) |
| MasterOutputTrigger | `TIM_TRGO_ENABLE` | CR2.MMS | 1 | inherited | TIMx_CR1.CEN bit is used as trigger output (TRGO) |
| MasterOutputTrigger | `TIM_TRGO_OC1` | CR2.MMS | 3 | inherited | Capture or compare match 1 is used as trigger outp |
| MasterOutputTrigger | `TIM_TRGO_OC1REF` | CR2.MMS | 4 | inherited | OC1REF signal is used as trigger output(TRGO) |
| MasterOutputTrigger | `TIM_TRGO_OC2REF` | CR2.MMS | 5 | inherited | OC2REF signal is used as trigger output(TRGO) |
| MasterOutputTrigger | `TIM_TRGO_OC3REF` | CR2.MMS | 6 | inherited | OC3REF signal is used as trigger output(TRGO) |
| MasterOutputTrigger | `TIM_TRGO_OC4REF` | CR2.MMS | 7 | inherited | OC4REF signal is used as trigger output(TRGO) |
| MasterOutputTrigger | `TIM_TRGO_RESET` | CR2.MMS | 0 | inherited | TIMx_EGR.UG bit is used as trigger output (TRGO) |
| MasterOutputTrigger | `TIM_TRGO_UPDATE` | CR2.MMS | 2 | inherited | Update event is used as trigger output (TRGO) |
| MasterOutputTrigger2 | `TIM_TRGO2_ENABLE` | CR2.MMS2 | 1 | inherited | TIMx_CR1.CEN bit is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC1` | CR2.MMS2 | 3 | inherited | Capture or a compare match 1 is used as trigger ou |
| MasterOutputTrigger2 | `TIM_TRGO2_OC1REF` | CR2.MMS2 | 4 | inherited | OC1REF signal is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC2REF` | CR2.MMS2 | 5 | inherited | OC2REF signal is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC3REF` | CR2.MMS2 | 6 | inherited | OC3REF signal is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC4REF` | CR2.MMS2 | 7 | inherited | OC4REF signal is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC4REF_RISINGFALLING` | CR2.MMS2 | 10 | inherited | OC4REF rising or falling edges generate pulses on  |
| MasterOutputTrigger2 | `TIM_TRGO2_OC4REF_RISING_OC6REF_FALLING` | CR2.MMS2 | 13 | inherited | OC4REF rising or OC6REF falling edges generate pul |
| MasterOutputTrigger2 | `TIM_TRGO2_OC4REF_RISING_OC6REF_RISING` | CR2.MMS2 | 12 | inherited | OC4REF or OC6REF rising edges generate pulses on T |
| MasterOutputTrigger2 | `TIM_TRGO2_OC5REF` | CR2.MMS2 | 8 | inherited | OC5REF signal is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC5REF_RISING_OC6REF_FALLING` | CR2.MMS2 | 15 | inherited | OC5REF rising or OC6REF falling edges generate pul |
| MasterOutputTrigger2 | `TIM_TRGO2_OC5REF_RISING_OC6REF_RISING` | CR2.MMS2 | 14 | inherited | OC5REF or OC6REF rising edges generate pulses on T |
| MasterOutputTrigger2 | `TIM_TRGO2_OC6REF` | CR2.MMS2 | 9 | inherited | OC6REF signal is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_OC6REF_RISINGFALLING` | CR2.MMS2 | 11 | inherited | OC6REF rising or falling edges generate pulses on  |
| MasterOutputTrigger2 | `TIM_TRGO2_RESET` | CR2.MMS2 | 0 | inherited | TIMx_EGR.UG bit is used as trigger output (TRGO2) |
| MasterOutputTrigger2 | `TIM_TRGO2_UPDATE` | CR2.MMS2 | 2 | inherited | Update event is used as trigger output (TRGO2) |
| OCIdleState | `TIM_OCIDLESTATE_RESET` | CR2.OIS1 | 0 | inherited | Output Idle state: OCx=0 when MOE=0 |
| OCIdleState | `TIM_OCIDLESTATE_RESET` | CR2.OIS1 | 0 | inherited | Output Idle state: OCx=0 when MOE=0 |
| OCIdleState | `TIM_OCIDLESTATE_SET` | CR2.OIS1 | 1 | inherited | Output Idle state: OCx=1 when MOE=0 |
| OCIdleState | `TIM_OCIDLESTATE_SET` | CR2.OIS1 | 1 | inherited | Output Idle state: OCx=1 when MOE=0 |
| OCNIdleState | `TIM_OCNIDLESTATE_RESET` | CR2.OIS1N | 0 | inherited | Complementary output Idle state: OCxN=0 when MOE=0 |
| OCNIdleState | `TIM_OCNIDLESTATE_RESET` | CR2.OIS1N | 0 | inherited | Complementary output Idle state: OCxN=0 when MOE=0 |
| OCNIdleState | `TIM_OCNIDLESTATE_SET` | CR2.OIS1N | 1 | inherited | Complementary output Idle state: OCxN=1 when MOE=0 |
| OCNIdleState | `TIM_OCNIDLESTATE_SET` | CR2.OIS1N | 1 | inherited | Complementary output Idle state: OCxN=1 when MOE=0 |
| OCNPolarity | `TIM_OCNPOLARITY_HIGH` | CCER.CC1NP | 0 | inherited | Capture/Compare complementary output polarity |
| OCNPolarity | `TIM_OCNPOLARITY_HIGH` | CCER.CC1NP | 0 | inherited | Capture/Compare complementary output polarity |
| OCNPolarity | `TIM_OCNPOLARITY_LOW` | CCER.CC1NP | 1 | inherited | Capture/Compare complementary output polarity |
| OCNPolarity | `TIM_OCNPOLARITY_LOW` | CCER.CC1NP | 1 | inherited | Capture/Compare complementary output polarity |
| OCPolarity | `TIM_OCPOLARITY_HIGH` | CCER.CC1P | 0 | inherited | Capture/Compare output polarity |
| OCPolarity | `TIM_OCPOLARITY_HIGH` | CCER.CC1P | 0 | inherited | Capture/Compare output polarity |
| OCPolarity | `TIM_OCPOLARITY_LOW` | CCER.CC1P | 1 | inherited | Capture/Compare output polarity |
| OCPolarity | `TIM_OCPOLARITY_LOW` | CCER.CC1P | 1 | inherited | Capture/Compare output polarity |
| OnePulseMode | `TIM_OPMODE_REPETITIVE` | CR1.OPM | 0 | inherited |  |
| OnePulseMode | `TIM_OPMODE_SINGLE` | CR1.OPM | 1 | inherited |  |
| Position | `TIM_ENCODERINDEX_POSITION_0` | ECR.IPOS | 0 | inherited |  |
| Position | `TIM_ENCODERINDEX_POSITION_00` | ECR.IPOS | 0 | inherited |  |
| Position | `TIM_ENCODERINDEX_POSITION_01` | ECR.IPOS | 1 | inherited |  |
| Position | `TIM_ENCODERINDEX_POSITION_1` | ECR.IPOS | 1 | inherited |  |
| Position | `TIM_ENCODERINDEX_POSITION_10` | ECR.IPOS | 2 | inherited |  |
| Position | `TIM_ENCODERINDEX_POSITION_11` | ECR.IPOS | 3 | inherited |  |
| Prescaler | `TIM_ENCODERINDEX_PRESCALER_DIV1` | SMCR.ETPS | 0 | inherited |  |
| Prescaler | `TIM_ENCODERINDEX_PRESCALER_DIV2` | SMCR.ETPS | 1 | inherited |  |
| Prescaler | `TIM_ENCODERINDEX_PRESCALER_DIV4` | SMCR.ETPS | 2 | inherited |  |
| Prescaler | `TIM_ENCODERINDEX_PRESCALER_DIV8` | SMCR.ETPS | 3 | inherited |  |
| SlaveMode | `TIM_SLAVEMODE_DISABLE` | SMCR.SMS | 0 | inherited | Slave mode disabled |
| SlaveMode | `TIM_SLAVEMODE_EXTERNAL1` | SMCR.SMS | 7 | inherited | External Clock Mode 1 |
| SlaveMode | `TIM_SLAVEMODE_GATED` | SMCR.SMS | 5 | inherited | Gated Mode |
| SlaveMode | `TIM_SLAVEMODE_RESET` | SMCR.SMS | 4 | inherited | Reset Mode |
| SlaveMode | `TIM_SLAVEMODE_TRIGGER` | SMCR.SMS | 6 | inherited | Trigger Mode |
| Source | `TIM_BREAKINPUTSOURCE_BKIN` | AF1.BKINE | 1 | llm_inferred |  |
| Source | `TIM_BREAKINPUTSOURCE_COMP1` | AF1.BKCMP1E | 1 | llm_inferred |  |
| Source | `TIM_BREAKINPUTSOURCE_COMP2` | AF1.BKCMP2E | 1 | llm_inferred |  |
| Source | `TIM_BREAKINPUTSOURCE_COMP3` | AF1.BKCMP3E | 1 | llm_inferred |  |
| Source | `TIM_BREAKINPUTSOURCE_COMP4` | AF1.BKCMP4E | 1 | llm_inferred |  |
| TriggerPrescaler | `TIM_TRIGGERPRESCALER_DIV1` | SMCR.ETPS | 0 | inherited | No prescaler is used |
| TriggerPrescaler | `TIM_TRIGGERPRESCALER_DIV2` | SMCR.ETPS | 1 | inherited | Prescaler for External ETR Trigger: Capture perfor |
| TriggerPrescaler | `TIM_TRIGGERPRESCALER_DIV4` | SMCR.ETPS | 2 | inherited | Prescaler for External ETR Trigger: Capture perfor |
| TriggerPrescaler | `TIM_TRIGGERPRESCALER_DIV8` | SMCR.ETPS | 3 | inherited | Prescaler for External ETR Trigger: Capture perfor |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| PulseWidth | 0..255 | 待定 | IS_TIM_PULSEONCOMPARE_WIDTH |
| PulseWidthPrescaler | 0..7 | 待定 | IS_TIM_PULSEONCOMPARE_WIDTHPRESCALER |
| Deadtime | 0..255 | 待定 | IS_TIM_DEADTIME |
| FallingDeadtime | 0..255 | 待定 | IS_TIM_DEADTIME |
| ICFilter | 0..15 | 待定 | IS_TIM_IC_FILTER |
| ICFilter | 0..15 | 待定 | IS_TIM_IC_FILTER |
| IC2Filter | 0..15 | 待定 | IS_TIM_IC_FILTER |
| ClockFilter | 0..15 | 待定 | IS_TIM_CLOCKFILTER |
| ClearInputFilter | 0..15 | 待定 | IS_TIM_CLEARINPUT_FILTER |
| TriggerFilter | 0..15 | 待定 | IS_TIM_TRIGGERFILTER |
| Filter | 0..15 | 待定 | IS_TIM_ENCODERINDEX_FILTER |
| PulseWidth | 0..255 | 待定 | IS_TIM_PULSEONCOMPARE_WIDTH |
| PulseWidthPrescaler | 0..7 | 待定 | IS_TIM_PULSEONCOMPARE_WIDTHPRESCALER |
| Deadtime | 0..255 | 待定 | IS_TIM_DEADTIME |
| FallingDeadtime | 0..255 | 待定 | IS_TIM_DEADTIME |
| FirstIndexEnable | 0..1 | 待定 | FunctionalState |
| Prescaler | 自由值 | PSC.(整寄存器) | 扫描 |
| Period | 自由值 | ARR.(整寄存器) | 扫描 |
| RepetitionCounter | 自由值 | RCR.(整寄存器) | 扫描 |
| Pulse | 0..65535 | CCR1.CCR1 | llm_inferred |
| Pulse | 0..65535 | CCR2.CCR2 | llm_inferred |
| Pulse | 0..65535 | CCR3.CCR3 | llm_inferred |
| Pulse | 0..65535 | CCR4.CCR4 | llm_inferred |
| Pulse | 0..65535 | CCR5.CCR5 | llm_inferred |
| Pulse | 0..65535 | CCR6.CCR6 | llm_inferred |
| IC1Filter | 0..15 | CCMR1.IC1F | llm_inferred |
| ClearInputState | 0..1 | CCMR1.OC1CE | llm_inferred |
| ClearInputState | 0..1 | CCMR1.OC2CE | llm_inferred |
| ClearInputState | 0..1 | CCMR2.OC3CE | llm_inferred |
| ClearInputState | 0..1 | CCMR2.OC4CE | llm_inferred |
| ClearInputState | 0..1 | CCMR3.OC5CE | llm_inferred |
| ClearInputState | 0..1 | CCMR3.OC6CE | llm_inferred |
| Commutation_Delay | 0..65535 | CCR2.CCR2 | llm_inferred |
| Polarity | 0..1 | CCER.CC1P | llm_inferred |
| Polarity | 0..1 | CCER.CC2P | llm_inferred |
| OutputChannel | 0..1 | CCER.CC1E | llm_inferred |
| OutputChannel | 0..1 | CCER.CC2E | llm_inferred |
| InputChannel | 0..3 | CCMR1.CC1S | llm_inferred |
| BurstBaseAddress | 0..31 | DCR.DBA | llm_inferred |

## UART

置信度计数:inherited=14

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| MsbFirst | `UART_MSB_FIRST_DISABLE` | CR1.MSBFIRST | 0 | inherited |  |
| MsbFirst | `UART_MSB_FIRST_ENABLE` | CR1.MSBFIRST | 1 | inherited |  |
| Parity | `UART_PARITY_NONE` | CR1.PCE | 0 | inherited |  |
| Parity | `UART_PARITY_ODD` | CR1.PCE | 1 | inherited |  |
| RxMode | `UART_RX_ADDR_MATCH_HARD` | CR3.ADDR_MATCH | 1 | inherited |  |
| RxMode | `UART_RX_ADDR_MATCH_SOFT` | CR3.ADDR_MATCH | 0 | inherited |  |
| StopBits | `UART_STOPBITS_1` | CR1.STOP | 0 | inherited |  |
| StopBits | `UART_STOPBITS_1_5_OR_2` | CR1.STOP | 1 | inherited |  |
| TxMode | `UART_TX_MODE_0` | CR3.TX_MODE | 0 | inherited |  |
| TxMode | `UART_TX_MODE_1` | CR3.TX_MODE | 1 | inherited |  |
| WordLength | `UART_WORDLENGTH_5B` | CR1.M | 0 | inherited |  |
| WordLength | `UART_WORDLENGTH_6B` | CR1.M | 1 | inherited |  |
| WordLength | `UART_WORDLENGTH_7B` | CR1.M | 2 | inherited |  |
| WordLength | `UART_WORDLENGTH_8B` | CR1.M | 3 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| RxMatchAddr | 0..255 | RAR.RAR | IS_UART_RX_MATCH_ADDR |
| BaudRate | 0..65535 | BRR.BRR | llm_inferred |
| BaudRate | 0..15 | BRRF.BRRF | llm_inferred |

## USART

置信度计数:direct=4, inherited=24

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| CLKLastBit | `USART_LASTBIT_DISABLE` | CR2.LBCL | 0 | inherited | USART frame last data bit clock pulse not output t |
| CLKLastBit | `USART_LASTBIT_ENABLE` | CR2.LBCL | 1 | inherited | USART frame last data bit clock pulse output to SC |
| CLKPhase | `USART_PHASE_1EDGE` | CR2.CPHA | 0 | inherited | USART frame phase on first clock transition |
| CLKPhase | `USART_PHASE_2EDGE` | CR2.CPHA | 1 | inherited | USART frame phase on second clock transition |
| CLKPolarity | `USART_POLARITY_HIGH` | CR2.CPOL | 1 | inherited | Driver enable signal is active low |
| CLKPolarity | `USART_POLARITY_LOW` | CR2.CPOL | 0 | inherited | Driver enable signal is active high |
| Parity | `USART_PARITY_EVEN` | CR1.PCE | 1 | inherited | Even parity |
| Parity | `USART_PARITY_NONE` | CR1.PCE | 0 | inherited | No parity |
| StopBits | `USART_STOPBITS_0_5` | CR2.STOP | 1 | inherited | USART frame with 0.5 stop bit |
| StopBits | `USART_STOPBITS_1` | CR2.STOP | 0 | inherited | USART frame with 1 stop bit |
| StopBits | `USART_STOPBITS_1_5` | CR2.STOP | 3 | inherited | USART frame with 1.5 stop bits |
| StopBits | `USART_STOPBITS_2` | CR2.STOP | 2 | inherited | USART frame with 2 stop bits |
| Threshold | `USART_RXFIFO_THRESHOLD_1_2` | CR1.RXFTCFG | 2 | inherited |  |
| Threshold | `USART_RXFIFO_THRESHOLD_1_4` | CR1.RXFTCFG | 1 | inherited |  |
| Threshold | `USART_RXFIFO_THRESHOLD_1_8` | CR1.RXFTCFG | 0 | inherited |  |
| Threshold | `USART_RXFIFO_THRESHOLD_3_4` | CR1.RXFTCFG | 3 | inherited |  |
| Threshold | `USART_RXFIFO_THRESHOLD_7_8` | CR1.RXFTCFG | 4 | inherited |  |
| Threshold | `USART_RXFIFO_THRESHOLD_8_8` | CR1.RXFTCFG | 5 | inherited |  |
| Threshold | `USART_TXFIFO_THRESHOLD_1_2` | CR1.TXFTCFG | 2 | inherited |  |
| Threshold | `USART_TXFIFO_THRESHOLD_1_4` | CR1.TXFTCFG | 1 | inherited |  |
| Threshold | `USART_TXFIFO_THRESHOLD_1_8` | CR1.TXFTCFG | 0 | inherited |  |
| Threshold | `USART_TXFIFO_THRESHOLD_3_4` | CR1.TXFTCFG | 3 | inherited |  |
| Threshold | `USART_TXFIFO_THRESHOLD_7_8` | CR1.TXFTCFG | 4 | inherited |  |
| Threshold | `USART_TXFIFO_THRESHOLD_8_8` | CR1.TXFTCFG | 5 | inherited |  |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| BaudRate | 0..4500000 | BRR.(整寄存器) | IS_USART_BAUDRATE |

## WWDG

置信度计数:inherited=6

| InitField | 符号 | 落点 | 值 | 置信度 | 描述 |
|---|---|---|---|---|---|
| EWIMode | `WWDG_EWI_DISABLE` | CFR.EWI | 0 | inherited | EWI Disable |
| EWIMode | `WWDG_EWI_ENABLE` | CFR.EWI | 1 | inherited | EWI Enable |
| Prescaler | `WWDG_PRESCALER_1` | CFR.WDGTB | 0 | inherited | WWDG counter clock = (PCLK1/4096)/1 |
| Prescaler | `WWDG_PRESCALER_2` | CFR.WDGTB | 1 | inherited | WWDG counter clock = (PCLK1/4096)/2 |
| Prescaler | `WWDG_PRESCALER_4` | CFR.WDGTB | 2 | inherited | WWDG counter clock = (PCLK1/4096)/4 |
| Prescaler | `WWDG_PRESCALER_8` | CFR.WDGTB | 3 | inherited | WWDG counter clock = (PCLK1/4096)/8 |

数值字段(范围/落点):

| InitField | 范围 | 落点 | 来源 |
|---|---|---|---|
| Window | 自由值 | CFR.(整寄存器) | 扫描 |
| Counter | 自由值 | CR.(整寄存器) | 扫描 |

## 全局置信度统计

- inherited: 691
- llm_inferred: 195
- direct: 175
- c_placement: 51

## 未覆盖余账(全部已归因)

| 外设 | 字段 | 状态 | 归因 |
|---|---|---|---|
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Channel | sentinel_only | 个案 |
| DAC | Alignment | ref_empty | 个案 |
| FDCAN | IdType | sentinel_only | 个案 |
| FDCAN | FilterIndex | no_ref | 个案 |
| FDCAN | FilterType | sentinel_only | 个案 |
| FDCAN | FilterConfig | sentinel_only | 个案 |
| FDCAN | FilterID1 | no_ref | 个案 |
| FDCAN | FilterID2 | no_ref | 个案 |
| FLASH | PageAddress | no_ref | 函数参数/循环计数,不写寄存器 |
| FLASH | NbPages | no_ref | 函数参数/循环计数,不写寄存器 |
| FLASH | SectorAddress | no_ref | 函数参数/循环计数,不写寄存器 |
| FLASH | NbSectors | no_ref | 函数参数/循环计数,不写寄存器 |
| FLASH | UserDataAddress | no_ref | 函数参数/循环计数,不写寄存器 |
| FLASH | OptionType | sentinel_only | selector→composer |
| FLASH | RDPLevel | ref_empty | 函数参数/循环计数,不写寄存器 |
| GPIO | Pin | sentinel_only | selector→composer |
| I2C | MemAddSize | sentinel_only | 个案 |
| I2C | MemAddSize | sentinel_only | 个案 |
| I2C | MemAddSize | sentinel_only | 个案 |
| I2C | MemAddSize | sentinel_only | 个案 |
| I2C | MemAddSize | sentinel_only | 个案 |
| I2C | MemAddSize | sentinel_only | 个案 |
| LPUART | AdvFeatureInit | sentinel_only | selector→composer |
| PWR | Mode | sentinel_only | 个案 |
| PWR | SLEEPEntry | sentinel_only | 个案 |
| PWR | STOPEntry | ref_empty | 个案 |
| RCC | OscillatorType | sentinel_only | selector→composer |
| RCC | ClockType | sentinel_only | selector→composer |
| RCC | PeriphClockSelection | ref_empty | 个案 |
| RCC | RCC_MCOx | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| RTC | Format | sentinel_only | 个案 |
| SCI | AdvFeatureInit | sentinel_only | selector→composer |
| SCI | AddressLength | ref_empty | 个案 |
| SMARTCARD | AdvFeatureInit | ref_empty | selector→composer |
| TIM | Pulse | no_ref | 个案 |
| TIM | IC1Filter | no_ref | 个案 |
| TIM | Polarity | ref_empty | 个案 |
| TIM | Channel | sentinel_only | 个案 |
| TIM | Channel | sentinel_only | 个案 |
| TIM | Channel | sentinel_only | 个案 |
| TIM | BurstLength | sentinel_only | 个案 |
| TIM | BurstLength | sentinel_only | 个案 |
| TIM | Channel | sentinel_only | 个案 |
| TIM | BreakInput | sentinel_only | 个案 |
| TIM | BreakInput | sentinel_only | 个案 |
| TIM | BreakInput | sentinel_only | 个案 |