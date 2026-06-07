# State of the art: emotion and vocal-event detection for Voice AI agents

As of June 2026, voice emotion detection is usable for adapting an agent’s behaviour, routing calls, or highlighting moments for review. It is not reliable enough to treat as a direct measurement of a person’s internal emotional state.

A production system should describe **perceived vocal expressions** with confidence scores rather than assert statements such as “the caller is angry.” Hume’s documentation explicitly warns that vocal expressions should not be treated as direct inferences of emotional experience. The limitation remains visible on naturalistic benchmarks: in the INTERSPEECH 2025 Speech Emotion Recognition Challenge, the best submitted system achieved a macro-F1 score of approximately **0.43** across eight emotion categories on spontaneous podcast audio. ([Hume AI][1])

## 1. Separate the problem into distinct layers

A transcript sentiment model alone is insufficient. It may understand that the words “this is fantastic” are positive, but it can miss sarcasm, nervous laughter, a distressed tone, or crying between words.

| Layer                         | What it detects                                                                      | Suitable outputs                                          |
| ----------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| Speech emotion recognition    | Sadness, joy, anger, fear, surprise, frustration, calmness, excitement               | Multi-label expression scores; dominant label; confidence |
| Dimensional affect estimation | Intensity and emotional direction                                                    | Valence, arousal and dominance scores                     |
| Vocal-event detection         | Laughter, giggling, sobbing, crying, sighing, coughing, groaning, moaning, screaming | Timestamped event labels with confidence                  |
| Transcript analysis           | Sentiment, intent, topic, escalation language                                        | Text-based scores and intent classification               |
| Conversation-level analysis   | Emotional trajectory across several turns                                            | Smoothed per-speaker state and significant changes        |

“Excitement” is often better represented as relatively high arousal combined with positive valence than as a single rigid category. Similarly, “moaning” should be treated as a vocal event, not as proof of pain, pleasure, distress, or any other cause. The acoustic signal alone is ambiguous.

The INTERSPEECH benchmark uses both categorical emotion labels and dimensional ratings for arousal, valence and dominance, which reflects this dual approach. ([Multimodal Speech Processing Laboratory][2])

## 2. Current best-performing methods

### Speech emotion recognition

The strongest modern systems generally use a pretrained speech encoder rather than handcrafted audio features alone. Common foundations include wav2vec 2.0, HuBERT, WavLM and emotion-specific models such as emotion2vec+. These models learn acoustic representations from large quantities of audio and are then fine-tuned for emotion labels or affect dimensions. Recent research also combines information from several internal encoder layers because emotion cues are distributed across pitch, rhythm, intensity, voice quality and higher-level speech representations. ([GitHub][3])

For a stronger production system, use parallel branches:

1. An acoustic branch for prosody and vocal expression.
2. An audio-event branch for laughter, crying and other non-speech sounds.
3. A transcription branch for semantic meaning.
4. A temporal fusion layer that considers the previous turns and smooths unstable predictions.

Recent research systems increasingly fuse speech and transcript information. Speech-language models are also emerging, but current evidence suggests that zero-shot speech-LLM classification remains sensitive to prompting and can underperform supervised models on strict emotion-label accuracy. ([arXiv][4])

### Vocal-event detection

For laughter, crying and similar events, use an audio-event detection model alongside the emotion model.

General audio classifiers such as YAMNet predict hundreds of AudioSet classes. AudioSet explicitly includes categories such as laughter and crying or sobbing. This is a useful baseline for rapid prototyping, but it is not sufficiently granular for every voice-agent requirement. ([TensorFlow][5])

For fine distinctions such as:

* laughter versus giggling;
* crying versus sobbing;
* breathing versus sighing;
* groaning versus moaning;
* speech mixed with laughter;

you will usually need a specialist classifier fine-tuned on annotated recordings from your target environment.

The VocalSound dataset is useful for this purpose. It contains more than 21,000 crowdsourced recordings of human vocal sounds, including laughter, sighing, coughing, throat clearing, sneezing and sniffing. It does not cover every granular event, so custom data will still be needed for cases such as giggling and moaning. ([arXiv][6])

## 3. Relevant providers

There is no universally best provider. The right option depends on whether you need live streaming, multilingual support, on-premise deployment, precise vocal-event labels or low latency.

| Provider                            | Appropriate use                                         | Strengths                                                                                                                                                                                                   | Important caveat                                                                                                                                                                                |
| ----------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Inworld STT Voice Profiles**      | Live voice-agent MVP                                    | Returns transcript alongside structured emotion, pitch, accent and vocal-style predictions. Vocal styles include crying, laughing, shouting, whispering and singing. Supports HTTP and WebSocket streaming. | Confirm language coverage for your selected model. Inworld’s May 2026 material states that profiling through `inworld/inworld-stt-1` is currently English-only. ([Inworld AI Documentation][7]) |
| **audEERING devAIce**               | Enterprise, on-device and privacy-sensitive deployments | Vocal-expression analysis, acoustic-scene detection, voice activity detection and feature extraction. Designed for low-resource real-time use, including embedded devices.                                  | Primarily an enterprise SDK and integration decision rather than a plug-and-play developer API. ([audEERING][8])                                                                                |
| **Behavioral Signals**              | Contact centres and enterprise voice analytics          | Streaming and batch analysis, behavioural metrics, speech-to-text, diarization and custom on-premise options.                                                                                               | Evaluate its exact emotion taxonomy and latency on your use case. It is broader than a specialist laughter or vocal-burst classifier. ([BehavioralSignals][9])                                  |
| **Imentiv**                         | Batch or post-call emotion analytics                    | Audio emotion analysis, valence estimation and speaker diarization.                                                                                                                                         | Review its streaming guarantees before using it for live turn-by-turn agent adaptation. ([imentiv.ai][10])                                                                                      |
| **Hume Expression Measurement API** | Reference taxonomy only                                 | Historically offered detailed speech-prosody and vocal-burst models. Its documented vocal-burst taxonomy includes laughter, giggling, crying, sobbing, groaning and moaning.                                | Do not start a new dependency on this API. Hume states that the Expression Measurement API is being sunset, with final use and result downloads ending on **June 14, 2026**. ([Hume AI][11])    |

Hume’s older taxonomy is still useful as a reference when designing your own event schema, even though the API itself is not a viable new dependency.

## 4. Relevant open-source libraries and models

| Library or model                        | Best use                                                            | Notes                                                                                                                                                                                                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **SenseVoice / FunASR**                 | Integrated prototype and self-hosted baseline                       | Combines speech recognition, language identification, speech emotion recognition and audio-event detection. Its documented events include laughter, crying, coughing, sneezing, applause and background music. SenseVoice-Small is designed for fast inference. ([GitHub][12]) |
| **emotion2vec+**                        | More specialized speech-emotion modelling                           | Emotion-focused pretrained representations with several model sizes. Useful when you want to fine-tune a stronger classifier for your own domain or language mix. ([GitHub][3])                                                                                                |
| **YAMNet**                              | Fast general-purpose audio-event baseline                           | TensorFlow model trained on AudioSet classes. Suitable for detecting broad categories such as laughter and crying before building a more precise classifier. ([TensorFlow][5])                                                                                                 |
| **openSMILE**                           | Interpretable acoustic features, diagnostics and lightweight models | Extracts features such as pitch, energy and voice-quality indicators. Useful for debugging, edge models and hybrid systems. Its licensing conditions differ between research and commercial usage. ([Audeering][13])                                                           |
| **SpeechBrain wav2vec2 emotion models** | Simple baseline and proof of concept                                | Easy to test, but common public checkpoints are often trained on acted datasets such as IEMOCAP. Do not assume that their benchmark accuracy will transfer to real customer calls. ([Hugging Face][14])                                                                        |

SenseVoice is the most convenient open-source starting point when you want one pipeline covering transcription, coarse emotion labels and common sound events. For more robust results, combine it with a separate event classifier and evaluate emotion2vec+ as a specialist acoustic branch.

## 5. What remains difficult

### Naturalistic generalization

Models perform substantially better on acted datasets than on uncontrolled conversations. Real calls contain background noise, interruptions, code-switching, poor microphones, varying emotional intensity and speakers who express emotions differently. The INTERSPEECH 2025 naturalistic benchmark’s best macro-F1 score of roughly 0.43 shows that eight-class emotion classification remains far from solved. ([Multimodal Speech Processing Laboratory][2])

### Ambiguous labels

There is no universally correct taxonomy. “Excited,” “happy,” “surprised,” “nervous” and “agitated” may overlap acoustically. A speaker can also sound calm while being angry, or laugh while uncomfortable. Expressions are not direct windows into mental state. ([Hume AI][1])

### Subtle and low-intensity emotions

High-arousal anger is generally easier to detect than quiet frustration, concentration, restrained sadness or discomfort. Research on fine-grained vocal emotion recognition continues to report difficulty separating related emotional states. ([arXiv][15])

### Vocal-event granularity

Broad events such as laughter and crying are easier than precise subcategories such as giggling, chuckling, sobbing, groaning and moaning. Sounds may overlap with words or background media. A domain-specific annotated dataset is usually necessary.

### Speaker, language and cultural variation

Emotion expression varies across accents, languages, cultures, ages, speaking styles and individual voices. Fairness studies continue to identify performance differences across demographic groups and trade-offs between aggregate accuracy and subgroup fairness. Atypical speech is also underrepresented in many datasets. ([arXiv][16])

### Latency versus context

A live agent must react quickly, but emotional interpretation improves when the model observes a longer window. Short chunks can cause unstable labels. Use rolling windows, confidence thresholds and hysteresis rather than changing the agent’s behaviour after every frame.

### Telephone audio quality

Telephone channels often use narrowband 8 kHz audio. This removes useful acoustic detail and can reduce performance compared with higher-quality 16 kHz or 48 kHz streams. Inworld’s documentation explicitly notes that telephony audio has fewer acoustic data points and produces lower-quality results. ([Inworld AI Documentation][17])

## 6. Recommended architecture for a Voice AI agent

For a first production-oriented version, use this pipeline:

```text
Incoming audio
   ↓
Noise handling + voice activity detection
   ↓
Speaker diarization
   ↓
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ Acoustic emotion     │ Vocal-event detector │ Speech recognition   │
│ model                │                      │ + transcript model   │
│ sadness, joy, anger  │ laugh, cry, sob,     │ sentiment, intent,   │
│ fear, arousal, etc.  │ giggle, moan, etc.   │ escalation language  │
└──────────────────────┴──────────────────────┴──────────────────────┘
   ↓
Temporal fusion and confidence calibration
   ↓
Per-speaker expression timeline
   ↓
Agent response policy
```

A suitable event object would look like this:

```json
{
  "speaker_id": "caller_01",
  "start_time": 12.4,
  "end_time": 15.1,
  "perceived_expressions": [
    {"label": "sadness", "score": 0.71},
    {"label": "frustration", "score": 0.48}
  ],
  "affect": {
    "valence": -0.54,
    "arousal": 0.39,
    "dominance": 0.22
  },
  "vocal_events": [
    {"label": "sobbing", "score": 0.81}
  ],
  "transcript_sentiment": "negative",
  "uncertain": false
}
```

The application logic should use these scores conservatively. For example:

* slow down the agent’s speaking pace when distress signals persist;
* ask a clarifying question when predictions are uncertain;
* route to a human operator after sustained escalation;
* record a timestamp for later review;
* avoid irreversible decisions based solely on inferred emotion.

## 7. Practical build choices

For a fast managed MVP, use **Inworld STT Voice Profiles** for live transcription and coarse vocal profiling, then add a custom audio-event classifier for labels such as giggling, sobbing, groaning and moaning.

For a self-hosted stack, use:

```text
SenseVoice-Small / FunASR
+ emotion2vec+ classifier
+ YAMNet or a fine-tuned vocal-event model
+ openSMILE features for debugging and model monitoring
+ voice activity detection and diarization
```

Start with a limited taxonomy. A realistic initial set is:

```text
Speech expressions:
neutral, joy, sadness, anger, fear, surprise, frustration, excitement

Vocal events:
laughter, giggling, crying, sobbing, sighing, groaning, moaning,
coughing, screaming, background speech, background music
```

Evaluate on your own audio rather than relying on public leaderboard scores. The test set should be speaker-disjoint and segmented by language, accent, audio channel, noise level and event type. Track macro-F1 for emotion categories, concordance correlation for dimensional affect, precision and recall for each vocal event, calibration quality, false-positive rates and end-to-end latency.

## 8. EU regulatory constraint

In the EU, this is also a product-design and compliance issue. The AI Act defines an emotion-recognition system as an AI system intended to identify or infer emotions or intentions based on biometric data. Its prohibited-practice rules already restrict emotion inference in workplaces and educational institutions, except for specified medical or safety reasons. The regulation itself highlights concerns around scientific validity, ambiguity, cultural variation, limited reliability and discriminatory outcomes. ([EUR-Lex][18])

For a consumer-facing voice agent, the safer framing is: analyse vocal expression to improve the interaction, disclose that the analysis occurs, obtain appropriate consent, store the minimum necessary data and avoid using predictions for consequential decisions. Legal review is necessary for the specific use case.

[1]: https://dev.hume.ai/docs/expression-measurement/science?utm_source=chatgpt.com "About the Science | Hume API"
[2]: https://lab-msp.com/MSP-Podcast_Competition/IS2025/ "Interspeech 2025: Speech Emotion Recognition Challenge"
[3]: https://github.com/ddlBoJack/emotion2vec "GitHub - ddlBoJack/emotion2vec: [ACL 2024] Official PyTorch code for extracting features and training downstream models with emotion2vec: Self-Supervised Pre-Training for Speech Emotion Representation · GitHub"
[4]: https://arxiv.org/abs/2506.02088?utm_source=chatgpt.com "Enhancing Speech Emotion Recognition with Graph-Based Multimodal Fusion and Prosodic Features for the Speech Emotion Recognition in Naturalistic Conditions Challenge at Interspeech 2025"
[5]: https://www.tensorflow.org/hub/tutorials/yamnet "Sound classification with YAMNet  |  TensorFlow Hub"
[6]: https://arxiv.org/abs/2205.03433?utm_source=chatgpt.com "Vocalsound: A Dataset for Improving Human Vocal Sounds Recognition"
[7]: https://docs.inworld.ai/stt/voice-profiles "Voice Profiles - Inworld AI Documentation"
[8]: https://www.audeering.com/products/devaice/?utm_source=chatgpt.com "devAIce"
[9]: https://platform.behavioralsignals.com/pricing/?utm_source=chatgpt.com "Pricing - BehavioralSignals API - Emotion and Behavioral ..."
[10]: https://imentiv.ai/apis/?utm_source=chatgpt.com "Emotion Recognition API Documentation"
[11]: https://dev.hume.ai/docs/expression-measurement/overview?utm_source=chatgpt.com "Expression Measurement - Hume API"
[12]: https://github.com/FunAudioLLM/SenseVoice "GitHub - FunAudioLLM/SenseVoice: Multilingual speech understanding: ASR + emotion recognition + audio event detection. 50+ languages, 15x faster than Whisper, non-autoregressive. · GitHub"
[13]: https://audeering.github.io/opensmile/ "openSMILE — openSMILE Documentation"
[14]: https://huggingface.co/speechbrain/emotion-recognition-wav2vec2-IEMOCAP?utm_source=chatgpt.com "speechbrain/emotion-recognition-wav2vec2-IEMOCAP"
[15]: https://arxiv.org/abs/2506.09827?utm_source=chatgpt.com "EmoNet-Voice: A Fine-Grained, Expert-Verified Benchmark for Speech Emotion Detection"
[16]: https://arxiv.org/pdf/2506.04652?utm_source=chatgpt.com "EMO-Debias: Benchmarking Gender Debiasing ..."
[17]: https://docs.inworld.ai/stt/overview?utm_source=chatgpt.com "Intro to Realtime STT"
[18]: https://eur-lex.europa.eu/legal-content/EN-DE/ALL/?from=EN&uri=CELEX%3A32024R1689 "Regulation - EU - 2024/1689 - EN - EUR-Lex"
