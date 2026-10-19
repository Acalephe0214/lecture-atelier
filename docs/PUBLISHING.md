# Source distributions / 源码打包

The distribution scripts export an explicit allowlist of source files. Runtime data, installed dependencies, model weights and Git history are excluded.

## Public source archive

Run from the repository root:

```sh
python3 prepare_github.py --output ../lecture-atelier-source --zip ../lecture-atelier-source.zip
```

Both output paths must be new. The generated directory and ZIP contain the same files, including documentation, tests, licenses and fictional examples. `SOURCE-MANIFEST.json` records each file's size and SHA-256 hash.

## User package

A smaller package includes the application, setup scripts, user guides and licenses, without developer tests:

```sh
python3 package_for_friends.py --output ../LectureAtelier.zip
```

The output ZIP must not already exist. `SHA256SUMS.txt` records file checksums. Runtime dependencies and models are downloaded separately by the optional installer.

## Release checklist

- Run the [software checks](VERIFICATION.md) and inspect both archives.
- Keep demonstrations fictional; exclude private recordings, transcripts, configuration, diagnostics and credentials.
- Preserve `LICENSE`, `THIRD-PARTY-NOTICES.txt` and `licenses/`.
- Rebuild archives and checksums after source changes. The allowlist and scanner complement a manual content review.
- Bundling third-party runtimes or binaries requires a separate license review; see [license notes](../licenses/README.md).

两个脚本均使用文件白名单，且不覆盖已有输出；不包含 Git 历史、模型、依赖环境或使用数据。源码包附开发文档和测试，使用包附安装脚本及中英文手册。修改源码后应重新生成包和校验清单。
