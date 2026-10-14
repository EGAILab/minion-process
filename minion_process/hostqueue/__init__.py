"""The host build queue (kit 0.4.0, `docs/p3b/`): one broker per host is the only writer of queue state.

Modules:

- `framing`: the record framing shared by the journal and the effect markers;
- `journal`: the append-only state journal;
- `markers`: write-ahead effect markers;
- `hostos`: the operating-system seam;
- `policy`: the host policy;
- `resources`: canonical resource identity and overlap;
- `state`: replayed queue state and admission;
- `broker`: the request loop, launch, end proof, recovery and repair;
- `client`: request and response files;
- `confirm`: the `CONFIRM QUEUE` hook;
- `jobspec`: frozen job inputs, slot binding and leases;
- `walk`: no-follow walks and the launch proof of writable resources;
- `runner`: the per-job process that executes a launcher.

There is no cleanup class in 0.4.0 (K-47); registered copies are removed only by hand (K-48'').
"""
