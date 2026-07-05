---
id: 29
title: 'Local browsing + network diagnosis: IP literals/.local/localhost default to h...'
state: DONE
created_at: 2026-07-04T19:49:41.085244-05:00
updated_at: 2026-07-04T19:49:41.085328-05:00
---

# Local browsing + network diagnosis: IP literals/.local/localhost default to http:// (bare-IP devices rarely speak TLS) and never get www-prepended (www.192.168.1.7 is not a thing); DNS-hang errors point at mdb doctor; new mdb doctor HOST — system resolver vs direct dig vs scutil scoped claims vs TCP reach, cross-read verdict. First reading nailed quantum.com: split-DNS claim with unreachable 10.x nameservers, fix = reboot (orphaned NetworkExtension holds resolver until then)

## Log

- 2026-07-05T00:49:41Z: Created task
