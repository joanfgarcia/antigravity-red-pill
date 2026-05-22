# Technical Architecture

Uses `watchfiles.awatch` to monitor folders defined in `cfg.INGESTION_DIRECTORIES`.
When a file is created or modified, it enqueues a `vectorize_file` task to the DAG `CognitiveQueueManager`.
