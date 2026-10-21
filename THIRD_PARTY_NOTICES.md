# Third-party notices and credits

Original project code and documentation are available under the repository's
[Apache License, Version 2.0](LICENSE). Each dependency retains its own license;
cited papers, websites, trademarks, and historical inspirations retain their own rights. The
bridge's original design copied no external source code or visual assets. The
mission exhibit includes the separately licensed, unchanged engine and NASA
files identified under Mission exhibit below.

## Runtime dependencies

This inventory follows the pinned production requirements.txt and the matching distributions installed in the project environment. Full license and notice files below are copied unchanged from those installed distributions. Development-only test dependencies are outside this production inventory.

| Package | Version | License | Full notice |
| --- | --- | --- | --- |
| [annotated-doc](https://github.com/fastapi/annotated-doc) | 0.0.5 | MIT | [LICENSE](licenses/annotated-doc-0.0.5/LICENSE) |
| [annotated-types](https://github.com/annotated-types/annotated-types) | 0.8.0 | MIT | [LICENSE](licenses/annotated-types-0.8.0/LICENSE) |
| [anyio](https://github.com/agronholm/anyio) | 4.15.1 | MIT | [LICENSE](licenses/anyio-4.15.1/LICENSE) |
| [click](https://github.com/pallets/click/) | 8.5.0 | BSD-3-Clause | [LICENSE.txt](licenses/click-8.5.0/LICENSE.txt) |
| [fastapi](https://github.com/fastapi/fastapi) | 0.142.2 | MIT | [LICENSE](licenses/fastapi-0.142.2/LICENSE) |
| [h11](https://github.com/python-hyper/h11) | 0.16.0 | MIT | [LICENSE.txt](licenses/h11-0.16.0/LICENSE.txt) |
| [idna](https://github.com/kjd/idna) | 3.20 | BSD-3-Clause | [LICENSE.md](licenses/idna-3.20/LICENSE.md) |
| [itsdangerous](https://github.com/pallets/itsdangerous/) | 2.2.0 | BSD-3-Clause | [LICENSE.txt](licenses/itsdangerous-2.2.0/LICENSE.txt) |
| [opentelemetry-api](https://github.com/open-telemetry/opentelemetry-python) | 1.45.1 | Apache-2.0 | [LICENSE](licenses/opentelemetry-api-1.45.1/LICENSE) |
| [pydantic](https://github.com/pydantic/pydantic) | 2.13.5 | MIT | [LICENSE](licenses/pydantic-2.13.5/LICENSE) |
| [pydantic-core](https://github.com/pydantic/pydantic/tree/main/pydantic-core) | 2.46.5 | MIT | [LICENSE](licenses/pydantic-core-2.46.5/LICENSE) |
| [starlette](https://github.com/Kludex/starlette) | 1.7.0 | BSD-3-Clause | [LICENSE.md](licenses/starlette-1.7.0/LICENSE.md) |
| [typing-extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | [LICENSE](licenses/typing-extensions-4.16.0/LICENSE) |
| [typing-inspection](https://github.com/pydantic/typing-inspection) | 0.4.4 | MIT | [LICENSE](licenses/typing-inspection-0.4.4/LICENSE) |
| [uvicorn](https://github.com/Kludex/uvicorn) | 0.54.0 | BSD-3-Clause | [LICENSE.md](licenses/uvicorn-0.54.0/LICENSE.md) |

## Python runtime

The inspected local interpreter is Python 3.12.14, under PSF-2.0 with the historical notices retained in its [complete bundled license](licenses/python-3.12.14/LICENSE.txt). This identifies the inspected interpreter, not an independently verified deployed runtime or every platform library.

## Design and research acknowledgements

### ELIZA / Joseph Weizenbaum

Joseph Weizenbaum’s 1966 ELIZA paper is the starting point for this conversational terminal homage. The monospace interface and quiet blue, gray, and black palette are an original interpretation.

Source: https://doi.org/10.1145/365153.365168

License / credit scope: Historical and visual inspiration; no ELIZA code or assets included.

### ENIAC

Penn’s account of ENIAC’s 1946 launch honors the people and work behind early electronic computing. The design lesson drawn here is to make controls and results clear.

Source: https://penntoday.upenn.edu/news/penns-eniac-worlds-first-electronic-computer-turns-80

License / credit scope: Historical inspiration; no historical code, photographs or assets included.

### IBM AS/400

IBM introduced the AS/400 in 1988, emphasizing ease of use, connectivity, and compatibility. AS/400 is the tentative match for Taylor’s remembered AS series.

Source: https://www.ibm.com/history/as-400

License / credit scope: Historical inspiration; no IBM code, trademarks as branding, or assets included.

### InfoDog and MB-F

A tribute to direct links, useful records, show information, and a community served over time. MB-F traces its dog-show business to 1900; InfoDog displays a 1996–2026 copyright range. The early computer vendor behind InfoDog remains unverified.

Source: https://www.infodog.com/

License / credit scope: Referenced website; its content and trademarks retain their own rights.

Upstream license or scope: https://www.infodog.com/my/tos.htm

### Jack Onofrio Dog Shows

A tribute to clear routes for entries, upcoming shows, results, and downloads. In a 2015 WEB400 post, Onofrio developer Joe W. Holt described an IBM i server using Apache and RPG/CGIDEV2. That first-person account records the system in use at the time.

Source: https://www.onofrio.com/

License / credit scope: Referenced website; no website code, images, or logos included.

### Sashiko

Roman Gushchin and colleagues developed Sashiko; its announcement credits Chris Mason’s separate review-prompts foundation. Its separation of threads, review stages, status and findings informed the original bridge, which copied no Sashiko source or assets. The separate mission exhibit retains DEGS's identified translation and its notices as test support, described below.

Source: https://sashiko.dev/

License / credit scope: Apache-2.0 (upstream software).

Upstream license or scope: https://github.com/sashiko-dev/sashiko/blob/main/LICENSE

### DEGS v2.1 Python translation

Taylor’s selected Python translation informed the original bridge's stage provenance and separate concern/result collections. The later mission exhibit includes the unchanged translation and prompts with DEGS's core test support. The retained upstream notices identify the authorship, modifications and license boundaries.

Source: https://github.com/tmccoy678/DEGS-v2.1

License / credit scope: MIT for original DEGS; Apache-2.0 for identified Sashiko-derived portions.

Upstream license or scope: https://github.com/tmccoy678/DEGS-v2.1/blob/main/THIRD_PARTY_NOTICES.md

The OpenAI and METR Hugging Face incident reports and Shapira and colleagues’ Agents of Chaos informed the separation of conversation, identity and execution authority. Their findings are cited as research context, not endorsement or validation of this app. Software and product names identify their respective projects and do not imply affiliation.

The complete APA-style citation data, source links, bibliographic qualifications and runtime inventory are in [references_data.json](references_data.json).

## Preservation record

All 16 retained license files were byte-compared with their installed originals. No third-party license text was rewritten. Dependency updates should refresh this inventory and recopy the corresponding original notices.
## Mission exhibit

`stage_vendor/DobeWorks` and `stage_vendor/DEGS` retain exact selected runtime files, core tests, fixtures and support files from the public repository commits identified in `stage_vendor/sources.json`. DobeWorks retains Apache-2.0 and its component-specific notices; original DEGS retains MIT and its identified Apache-derived portions retain their own notices. The exhibit does not relicense either project. DEGS's unmodified Sashiko translation and prompts retain its component-specific provenance and Apache notice; benchmark JSON fixtures retain their data license.

`stage_vendor/nasa-fprime` contains unmodified NASA/JPL F´ source at commit `a37ffa40871e567481d0a7626c12b24d8acdbf15`. Copyright 2025 California Institute of Technology; Apache-2.0. The CRC implementation's embedded Stephan Brumme provenance and permissive notice remain intact. See the retained `LICENSE.txt` and `provenance.json`. This is an F´ component, not a claim that NASA originated the CRC algorithm or endorses this exhibit.

The exhibit's original dialogue rules adapt keyword ranking, reassembly, and no-match fallback described by Joseph Weizenbaum in *ELIZA—A computer program for the study of natural language communication between man and machine* (1966), DOI `10.1145/365153.365168`. No original ELIZA program or paper text is vendored. The DobeWorks voice bank is retained unchanged with its original per-entry provenance and two identified short historical excerpts.
