# Backspace Gate browser demo source

Vendored from `tmccoy678/Backspace-Text-Retention` at commit
`32e87780c39dfe6137e032925e3090a356d88faa` under the same owner's Apache-2.0
project license.

The copied browser assets are served directly by DobeWorks at `/backspace`.
They contain no credentials, analytics, persistence API, external requests, or
private stream access. The Rust/WASM engine and JavaScript fallback are tested
for equivalent visible state, erase-run counts, compressed history, byte dump,
and final report in the source repository.

The local DobeWorks wrapper changes only asset URLs and adds the two public tabs.
