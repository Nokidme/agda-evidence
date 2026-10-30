# agda-stdlib pilot result — 30 October 2026

The initial real-project pilot completed successfully in [GitHub Actions run 41086824427](https://github.com/Nokidme/agda-evidence/actions/runs/41086824427). The workflow used the manual pilot configuration and pinned `agda/agda-stdlib` to commit `565739a4d82b8bb47d2f15cb99178db15ca60e9b`.

The uploaded evidence bundle was downloaded and verified independently with `agda-evidence verify` after the workflow completed. Its recorded gate is the upstream CI sequence: generate aggregate modules with deprecated modules included, typecheck `EverythingSafe.agda` under `--safe`, then typecheck `Everything.agda`. The explicit composite command exited with status `passed` and exit code `0`.

```text
sourceId:      sha256:5a64564ab914a6af0c4b3ec06b78a469fe382f9cfe9d158f220dd2efc2cbb295
resolutionId:  sha256:de2ba7a1a0fc7ae143b80f01afcecf8a662c381b9987a726938622d852d58c97
attestationId: sha256:131b56a04ea7defa8d5c63eb2110926d21ce622dbd032288da4efb398b6c6b50
bundleId:      sha256:5a0a4184d33659ea60666a84755c627a7c05b43eeb8020639700a025983c7e19
```

The bundle contains 1,417 source-file records. It observed `Agda version 2.8.0-3d04bac`, built with the compiler’s `optimise-heavily` flag.

The `sourceId` matches the separate local source-snapshot preflight of the same pinned tree. This demonstrates that the source comparison is insensitive to capture time and checkout path. The remote run has a different `resolutionId`, as expected: the preflight recorded no locally available Agda executable, whereas the workflow recorded its built Agda 2.8.0 binary and associated visible resolution context.

This result attests only the recorded command and source/environment evidence. The `resolutionId` remains partial; it does not prove an archived dependency closure, offline replayability, a cryptographic signature, or the informal mathematical meaning of the library. The bundle is retained as a GitHub Actions artifact for 30 days under the linked run.
