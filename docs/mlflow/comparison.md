Image-level damage-type detection on the held-out CarDD test split.

| Run | Type | test macro F1 | test micro F1 | test exact match | test mask mAP50-95 |
|---|---|---|---|---|---|
| baseline-prior | baseline | 0.110 | 0.394 | 0.222 | n/a |
| baseline-hog-logreg | baseline | 0.498 | 0.560 | 0.120 | n/a |
| yolov8n-seg | yolov8-seg | 0.811 | 0.837 | 0.639 | 0.490 |
