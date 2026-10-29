
# PA2 — Distributed Mini Discord: Implementation Milestones

**Status:** in progress. Scope reverted to exactly three servers (Oct 28,
2026); progress marks carried over from the Oct 27 review. M1 is mostly
done; M0 and M2–M4 are started. Due Oct 29, 2026. Carries over `Store`,
`Message`, and the `ERROR` hierarchy from PA1.

**Scope:** exactly three processes, A, B, and C, as the spec requires.
Addresses, ports, and priorities are read from `servers.json` (§2.2). The
channel ownership table is fixed by §2.1 and lives in `server.py`.

**Naming in this repo:** the peer-side class is `Peer` in `server.py`. An
unreachable peer raises `SERVICE_UNAVAILABLE` (503) directly, which takes
the place of a separate `PeerUnavailable`.

Legend: `[x]` done · `[~]` partial, see note · `[ ]` not started

Target layout:

    PA2-Miranda-Ricardo/
    ├── README.txt
    ├── MILESTONES.md          <- this file (optional in submission)
    ├── run.sh
    ├── servers.json           <- exactly as printed in §2.2
    ├── requirements.txt
    ├── server.py
    └── tests/
        ├── checkpoint_check.py
        └── test_store.py      <- adapted from PA1, optional

Currently `checkpoint_check.py` sits at the top level instead of in
`tests/`, and `requirements.txt` and `tests/` do not exist yet. Either move
the checker or update the commands below to match.

Workflow: implement one milestone, start the cluster with
`./run.sh --config servers.json`, run `python3 tests/checkpoint_check.py`,
fix what fails, move on. CP11 and CP12 need `--with-failure` and will ask
you to terminate Server C.

**Three rules that prevent most of the hard bugs:**

1. A `FORWARD` message that arrives over TCP is always processed locally.
   A server never forwards a forward. This is the loop prevention in §6.
2. Never hold the store lock across a peer call. Replication forms a cycle
   (A→B, B→C, C→A), so holding the lock while waiting for a backup's ACK
   can deadlock all three processes. Mutate under the lock, release, then
   replicate.
3. Ports and priorities come from `servers.json`, never from literals in
   `server.py`. The spec requires the implementation to read them from the
   file.

---

## Design

### Roles

| Role                   | Rule                                     | Server      |
| ---------------------- | ---------------------------------------- | ----------- |
| Cluster leader         | highest priority among available servers | C initially |
| User owner             | lowest priority in the config            | A           |
| Channel primary/backup | fixed table from §2.1                   | see below   |

Channel table, a module constant in `server.py`:

| Channel          | Primary | Backup |
| ---------------- | ------- | ------ |
| `#cs249`       | A       | B      |
| `#distributed` | B       | C      |
| `#systems`     | C       | A      |

The user owner is never the leader, so the demo's kill of C never takes
out user registration.

### Methods this plan uses

Config (module level):

- `load_config(path)` — parse `servers.json` and return the server entries
  keyed by id
- `validate_config(cfg)` — three servers; ids, ports, and priorities all
  unique. Exits with a clear message, not a traceback

On `Peer`:

- `peers_of_self()` — the two other server ids
- `primary_of(channel)` / `backup_of(channel)` — lookups in the channel table
- `alive_peers()` — snapshot of currently-available peer ids, taken under
  the state lock and returned as a copy
- `broadcast(obj, targets, timeout)` — sends to both peers and returns
  `{peer_id: response_or_SERVICE_UNAVAILABLE}`. Used by user sharing and
  leader announcements. Running the two calls in parallel keeps a dead peer
  from adding its timeout to every registration
- `compute_leader(available)` — pure function, `max` by priority

---

## M0 — Config and three-process startup

**Files:** `servers.json`, `run.sh`, `requirements.txt`, `server.py`
(bottom)
**Checker:** CP0, CP1

- [X] `servers.json` with the three servers from §2.2
- [ ] `load_config` and `validate_config`
- [ ] `server.py` accepts `--config` and `--id`
  - `main()` still has PA1's `--host`, `--tcp-port`, `--http-port`
- [ ] `--id` not present in the config is a startup error
- [ ] `run.sh --config <file>` starts A, B, and C as three background
  processes, each with its own `--id`
  - `run.sh` currently starts a single `server.py` in the foreground
- [ ] `trap` in `run.sh` kills all three PIDs on Ctrl-C
- [ ] `chmod +x run.sh` (can't be verified from the project copy)
- [ ] Every log line prefixed with the server id

- [~] `GET /health` returns `{"status":"ok","server_id":"<id>"}`
  - `do_GET` returns `{"status":"ok"}`; `server_id` is missing

- [X] No interactive input required at startup

**Done when:** `./run.sh --config servers.json` starts three separate
processes and each `/health` reports its own id.

---

## M1 — Port the PA1 store

**Files:** `server.py` (top section)
**Checker:** no CP coverage; `tests/test_store.py` covers it directly

- [X] Carry over `Store`, `Message`, `ERROR` and its seven subclasses
- [X] Add `SERVICE_UNAVAILABLE`, HTTP 503, for an unreachable primary or
  user owner
- [X] Add a `code -> exception class` lookup dict for rebuilding errors from
  a `FORWARD_RESPONSE`
  - Values are now the error classes, and `code_lookup` falls back to
    `SERVER_ERROR`. The dict is still named `code_to_status` and its
    comment still says "mapping code to status"; both describe the old
    version

- [~] `next_id` becomes per-channel — §4.10 requires ids unique within the
  channel, and each channel has one primary assigning them
  - `Store.post_message` uses `channel_message_id_tracker` correctly, but
    the counters are only created inside `Store.join` when it creates a
    missing channel. Once `join` stops creating channels (next item),
    counters must be seeded in `Store.__init__` or every send hits a
    `KeyError` (500)
  - Leftover `# self.next_id = 1` in `Store.__init__`

- [ ] Seed `#cs249`, `#distributed`, `#systems` at startup
  - `__init__` takes no arguments; `GET /channels` returns `[]`
  - `Store.join` still creates unknown channels; should raise `NOT_FOUND`
- [ ] Replica storage keyed by `(channel, message_id)`, separate from the
  primary message list
- [X] `Store` stays free of networking and server identity
  - Follow-up in `Peer`: `handle_peer_message` still calls
    `store.get_id()`, which `Store` doesn't have; the comments
    "Gets the id of this Store database" (after `peer_call`) and above
    `update_id` still describe the store; the `__init__` parameter named
    `Store` hides the class name

---

## M2 — Peer class and peer listener

**Files:** `server.py` (peer section)
**Checker:** CP2

- [~] `Peer` holds `self_id`, the loaded config, a reference to the
  `Store`, `alive` and `misses` dicts keyed by peer id, `current_leader`,
  and its own `state_lock`
  - Has id, priority, `cluster_config`, store, `alive`, `current_leader`
  - `misses` is a list (needs a dict); `state_lock = 0` (needs a real lock)

- [ ] `alive` and `misses` are initialized with the two other server ids
- [ ] Listener on this server's `peer_port`, thread per connection
  - Only PA1's text-command TCP server exists (`start_tcp_server`)

- [~] One JSON object per line in both directions
  - Client side done in `peer_call`; no listener side yet
- [~] `handle_peer_message` dispatches on `type`: PING, FORWARD, REPLICATE,
  LEADER_ANNOUNCE, USER_ADD
  - PING, FORWARD, REPLICATE, LEADER_ANNOUNCE branches exist, with
    `do_local_operation`, `store_replica`, `update_leader` as stubs
  - No USER_ADD branch
  - Reads `msg["request_id"]` for every message; PING has none, so every
    ping raises `KeyError`
- [~] `PING` -> `PONG` with `from` set to this id and `sequence` echoed
  - Returns a tuple, not a JSON object with `type`/`from`/`sequence`
  - Uses `store.get_id()` instead of this peer's id

- [ ] Unknown type gets a JSON error reply; a malformed line never kills the
  listener
  - Unknown type returns the `SERVER_ERROR` class itself, not a JSON reply

---

## M3 — Peer client and broadcast

**Files:** `server.py` (peer section)
**Checker:** underpins CP3 onward

- [~] `peer_call(target_id, obj, timeout)`: connect, send one line, read one
  line, close
  - Passes `target_id` straight to `socket.create_connection`, which needs
    a `(host, peer_port)` address looked up from the config
- [~] About 2s timeout; refused, timeout, and malformed reply all raise
  `SERVICE_UNAVAILABLE`
  - `create_connection` is outside the `try`, so a refused connection (a
    dead peer) escapes as `ConnectionRefusedError` instead of 503

- [ ] `broadcast(obj, targets, timeout)` calls `peer_call` for each target
  and collects results; a dead target never delays the other
- [ ] `alive_peers()` returns a copy taken under `state_lock`

---

## M4 — Heartbeats and process status

**Files:** `server.py`
**Checker:** CP3

- [ ] One daemon heartbeat thread per peer — two threads per server

- [~] PING every 2s, 2s response timeout, sequence verified
  - `Peer.heartbeat_loop` sends PING and checks `type` and `sequence`
  - No sleep between pings, so it spins as fast as it can
  - `finally: print("test")` prints on every iteration

- [ ] Three consecutive misses marks a peer unavailable; one success resets
  - No `except`, so the first failed ping raises out of the loop and ends
    the thread; misses are never counted
  - `self.misses[peer]` on a list raises `TypeError`
- [ ] Monitoring of the healthy peer continues after the other fails
- [ ] `GET /servers` lists A, B, and C, including this one
- [ ] Heartbeat work never blocks HTTP handling

---

## M5 — Leader selection

**Files:** `server.py`
**Checker:** CP4 (initial), CP12 (after failure)

- [ ] `compute_leader(available)` is `max` by priority — C leads initially
- [ ] A server always counts itself as available
- [ ] Recompute whenever a peer's availability changes
- [ ] When this server becomes leader, it sends `LEADER_ANNOUNCE` to
  `alive_peers()`
- [ ] Receiving `LEADER_ANNOUNCE` updates local leader state; ignore an
  announcement from a server this node currently believes is down
  - `Peer.update_leader` exists as a stub
- [ ] `GET /leader` returns `{"leader":"<id>","alive":true}`
- [ ] Leader selection never changes channel ownership

---

## M6 — User sharing

**Files:** `server.py` (HTTP section)
**Checker:** CP5, part of CP10

- [ ] User owner is A, the lowest-priority server in the config
- [ ] `POST /users` on B or C forwards to A
- [ ] A registers under the store lock, releases it, then `broadcast`s
  `USER_ADD` to `alive_peers()` **before returning 201**
- [ ] Broadcast skips a peer already marked down, so a dead server doesn't
  add a timeout to every registration
- [ ] `GET /users` answers from the local mirror
- [ ] Duplicates rejected globally, including concurrent registrations
  through different servers
- [X] Invalid username, missing field, malformed JSON rejected as in PA1
- [ ] Document in README.txt: if A dies, registration returns 503 while
  reads keep working off the mirrors. The demo kills C, so this never
  shows up in the recording

---

## M7 — Channel ownership and request forwarding

**Files:** `server.py` (HTTP section)
**Checker:** CP6, CP7

- [ ] Ownership comes from `primary_of` / `backup_of`, never an inline
  literal in a handler
- [ ] `GET /channels` lists all three channels on every server
- [ ] One `route_channel_op` helper for every channel endpoint
- [ ] One `do_local_operation` used by both HTTP and the `FORWARD` handler
  - `Peer.do_local_operation` exists as a stub
- [ ] Operations: JOIN, LEAVE, MEMBERS, SEND, HISTORY
- [ ] `request_id` generated per forward and echoed in `FORWARD_RESPONSE`
- [ ] Errors at the primary re-raised at the edge with the matching code
  - `code_lookup` (M1) is ready for this
- [ ] `SERVICE_UNAVAILABLE` from a peer call becomes 503
- [ ] Unknown channel — one not in the table — is NOT_FOUND locally, never
  forwarded
- [X] `unquote` each path segment after splitting (`unquote_segments`)

---

## M8 — Replication

**Files:** `server.py`
**Checker:** CP8

- [ ] After a local SEND at the primary, and after releasing the lock, send
  `REPLICATE` to `backup_of(channel)`
- [ ] Backup stores id, username, text unchanged and replies
  `REPLICATE_ACK`
  - `Peer.store_replica` exists as a stub
- [ ] Duplicate `REPLICATE` is acknowledged without a second record
- [ ] Primary stays operational when its backup is down
- [ ] `GET /replica/{channel}/messages` — local replica only, no forwarding,
  for demo Step 6
- [ ] Document sync vs async and when the client gets its 201

---

## M9 — Error handling

**Files:** `server.py` (HTTP section)
**Checker:** CP9

- [X] Unknown path -> 404 with the error envelope
- [ ] Unsupported method on a known path -> 404 or 405 with the envelope
- [ ] PUT/PATCH no longer return the base class's HTML 501 (open since PA1)

- [~] Invalid JSON, missing fields, unknown users, unknown channels, invalid
  names, unauthorized channel operations
  - Carried over from PA1; unknown channels still get created by `join`

- [ ] Unavailable peer -> 503, and no healthy server crashes

---

## M10 — Concurrency

**Files:** `server.py`
**Checker:** CP10

- [~] Threading HTTP server, thread per peer connection, heartbeat threads
  - Threading HTTP server done; the rest not started

- [ ] Concurrent registrations through any server cannot duplicate a name
- [ ] Concurrent sends to one channel get unique ids and a consistent order
- [ ] Concurrent membership changes do not corrupt state
- [ ] A slow or dead peer never permanently blocks a healthy process
- [ ] Document in README.txt: message order is insertion order at the
  primary under its lock

---

## M11 — Failure detection demo path

**Files:** `server.py`
**Checker:** CP11 (`--with-failure`)

- [ ] Terminating C leaves A and B running
- [ ] A and B both mark C unavailable within about 12s
- [ ] A and B still report each other available
- [ ] `#cs249` and `#distributed` keep working; `#systems` (owned by C)
  fails cleanly with an envelope rather than hanging

---

## M12 — Leader re-selection demo path

**Files:** `server.py`
**Checker:** CP12 (`--with-failure`)

- [ ] After C dies, A and B both select B
- [ ] B's `LEADER_ANNOUNCE` to A appears in the logs
- [ ] `GET /leader` on A and B both return `{"leader":"B","alive":true}`
- [ ] Channel ownership is unchanged; B does not take over `#systems`

---

## M13 — README and submission

**Files:** `README.txt`
**Checker:** manual

- [~] Student name, architecture, process configuration
  - Name and due date present; nothing else yet
- [~] Dependencies, setup, startup command
  - States stdlib only; no setup or startup command yet

- [ ] Role rules: leader = highest priority, user owner = A, channels from
  the §2.1 table
- [ ] User-sharing mechanism and what happens if A dies
- [ ] Forwarding design and the operation types beyond SEND
- [ ] Replication design, sync vs async, acknowledgement behavior
- [ ] Heartbeat interval, timeout, miss threshold
- [ ] Leader-selection mechanism and announcement message
- [ ] Concurrency, both locks, and the no-lock-across-peer-calls rule
- [ ] Testing instructions for the checker
- [ ] Video link or filename, and timestamps for each demo step
- [ ] No venvs, caches, compiled binaries, or credentials in the tarball
- [ ] `tar czvf PA2-Miranda-Ricardo.tar.gz PA2-Miranda-Ricardo/`

---

## M14 — Demo recording

**Checker:** manual

8–10 minutes, readable terminal and logs, name shown at the start.

1. `./run.sh --config servers.json` — show three separate processes
2. `/health` on 8101, 8102, 8103 — show each id
3. `/servers` on A, `/leader` on A and B — all alive, C is leader
4. Create alice on A, bob on B, read `/users` from C
5. Join and send for `#cs249` through C — show the forward in A's log
6. Read `#cs249` history from B, plus the local-replica endpoint on B
7. Terminate C, wait for the threshold, `/servers` on A and B
8. `/leader` on A and B both return B; show the `LEADER_ANNOUNCE` in logs

Do not edit out failures or error messages.
