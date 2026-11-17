# Trained models

Models are local and ignored by Git. A model is one JSON file: its training record with the
model inside. It loads only when a caller asks (`ranker=<path>`, or `ranker="auto"` for a model
packaged with a release) and its record shows the evaluation gate passed.
