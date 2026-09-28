# ARM64 release/toolchain consolidation audit

Audited branches:

- `fix/arm64-release-toolchain`
- `fix/arm64-flutter-source-install`

Target: current-main-based `feature/pcg1-passive-discovery`.

## Result

The final ARM64 source-install fix is already incorporated in the current prerelease workflow.

The older `fix/arm64-release-toolchain` branch used `subosito/flutter-action@v2` for both x64 and ARM64. The follow-up `fix/arm64-flutter-source-install` changed ARM64 to install Flutter directly from Flutter's stable Git repository while retaining the action for x64.

Current `.github/workflows/prerelease.yml` contains that final split exactly:

- Linux x64: `subosito/flutter-action@v2`, Flutter 3.47.2 stable.
- Linux ARM64: clone Flutter stable to `$RUNNER_TEMP/flutter`, add its bin directory to `$GITHUB_PATH`, and verify `flutter --version`.
- Both architectures run project generation, dependency resolution, tests, analysis, release build, and packaging.
- Windows x64 and Android are generated/tested/built in the same prerelease workflow.
- Current release metadata targets `main` and Alpha 5 rather than the obsolete PCG-1 foundation/Alpha 1 target.

## Supersession

- `fix/arm64-release-toolchain` — superseded by the source-install follow-up.
- `fix/arm64-flutter-source-install` — incorporated into current main.

Neither stale branch should be merged.

## Next parity gate

The toolchain consolidation itself is complete. The next repository gate is to validate
Android, Linux ARM64, and Windows x64 from one current commit and retain the workflow
artifacts/results tied to that SHA.
