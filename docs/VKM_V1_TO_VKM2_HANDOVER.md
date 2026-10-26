# VKM V1 to VKM2 Handover

## 1. Purpose and evidence boundary

This document records the public, non-secret handover baseline from the legacy
Vehicle Key Management System (VKM V1) to its successor, VKM2.

The statements below are separated into:

- **Verified facts**: confirmed from the VKM V1 source, Raspberry Pi
  configuration, or isolated hardware checks.
- **Migration policy**: the approved direction for integrating the verified
  hardware with VKM2.
- **Open items**: behavior that still requires VKM2 implementation or an
  end-to-end test.

The isolated checks did not modify the VKM V1 database or send test events to
the production application. A temporary GPIO pull configuration used for one
measurement was restored after the check.

## 2. Public information boundary

This repository is public. Do not add any of the following to this document,
issues, logs, screenshots, examples, or test fixtures:

- real RFID card identifiers or card payloads;
- names or other user information;
- the contents of the V1 user mapping file;
- SQLite database files or operational records;
- passwords, tokens, private keys, or other credentials;
- tunnel identifiers, real public hostnames, or private network addresses;
- personal home-directory paths or workstation-specific paths.

V1 user mappings and databases are not approved for automatic migration to
VKM2. Inventory and identities must be registered through a separately
approved, audited VKM2 procedure.

## 3. Legacy VKM V1 overview

VKM V1 was built to manage custody of vehicle keys and related items. Its
implemented capabilities included:

- RFID-based user identification;
- reed-switch detection of key removal and return;
- authenticated and unauthenticated custody states;
- key custody and vehicle-use records;
- a FastAPI and Jinja2 web interface;
- SQLite persistence; and
- CSV history export.

The legacy system used Python sensor processes on a Raspberry Pi and sent
events to a FastAPI application. This description is a handover record, not a
claim that every legacy feature was re-tested during the 2026 hardware check.

## 4. Verified hardware baseline

### 4.1 Raspberry Pi and Python

| Item | Verified baseline |
| --- | --- |
| Computer | Raspberry Pi 4 |
| Operating system | Raspbian GNU/Linux 12 (Bookworm) |
| Python | 3.11.2 |
| RFID reader | RC522 |
| RFID interface | SPI |
| Key-presence sensor | Reed switch |

### 4.2 RC522 and SPI

The RC522 reader used `mfrc522.SimpleMFRC522`. SPI was enabled, and the
standard SPI device nodes for bus 0 were present. An isolated read test on
2026-10-26 successfully initialized the reader and detected a card.

**Result: PASS**

The test demonstrates that:

- the RC522 can be initialized;
- SPI communication works with the existing hardware;
- a card can be detected with the existing wiring.

The test did not record or publish the card identifier or user mapping, and it
did not send an event to either VKM V1 or VKM2.

### 4.3 Reed switch

The verified reed-switch configuration is:

| Item | Value |
| --- | --- |
| GPIO numbering | BCM |
| GPIO | BCM17 |
| Raspberry Pi physical pin | 11 |
| Direction | Input |
| Bias | Internal pull-up |
| Key attached | LOW (`0`) |
| Key removed | HIGH (`1`) |

An isolated physical measurement on 2026-10-26 confirmed both signal states.

**Result: PASS**

The V1 monitor polled the input every 0.1 seconds. When it observed a change,
it waited 2 seconds and sampled the input again. It accepted the change only
when the second sample matched the first changed value.

This is a two-sample confirmation separated by 2 seconds. It is not proof that
the signal stayed continuously stable throughout the complete interval.

## 5. Verified V1 software baseline

The following versions were recorded from the V1 environment and dependency
file:

| Component | Version |
| --- | --- |
| Python | 3.11.2 |
| FastAPI | 0.135.2 |
| Uvicorn | 0.42.0 |
| Requests | 2.33.1 |
| RPi.GPIO | 0.7.1 |
| mfrc522 | 0.0.7 |
| spidev | 3.8 |
| python-multipart | 0.0.26 |
| Jinja2 | 3.1.6 |

These versions document the proven V1 environment. They are reference inputs,
not a requirement to copy the V1 dependency set into VKM2 unchanged.

### 5.1 FastAPI startup

The V1 FastAPI application was configured as a systemd service. The service:

- ran as a non-root application user;
- used the V1 project working directory and Python environment;
- started Uvicorn on port 8000;
- started during the normal multi-user boot sequence; and
- restarted the API process after a failure.

Observed service logs showed successful application startup and a successful
status request.

**FastAPI startup and status response: PASS**

The public handover intentionally omits the service's user-specific paths and
any network hostname.

### 5.2 Sensor process startup

Command history showed repeated direct execution of the RFID and reed-switch
programs. No dedicated sensor systemd unit or cron entry was found in the
reviewed evidence.

The sensors were therefore **likely started manually**, but their final
production startup order has not been proven. A legacy helper script that was
reviewed did not directly start both sensor programs and is not treated as
evidence of the production startup sequence.

## 6. V1 event behavior and limitations

The V1 RFID process read a card, mapped it through a local user file, sent an
HTTP request, and waited 3 seconds before its next cycle. The public handover
does not retain the mapping values or endpoint hostname.

The V1 reed-switch process sent one event for an attached key and another for
a removed key after its two-sample confirmation.

Important V1 limitations to address in VKM2 are:

- no verified durable queue for events that could not be delivered;
- no verified retry policy after a request failure;
- state could be advanced locally before delivery was confirmed;
- no verified stable event identifier for idempotent processing;
- no verified prevention of two sensor monitor instances running together;
- no verified startup reconciliation between physical state and stored state;
- no verified coordinated automatic startup for both sensor processes.

## 7. VKM2 migration architecture

### 7.1 Approved responsibility split

VKM2 will separate server and hardware responsibilities:

| Component | Runtime | Responsibility |
| --- | --- | --- |
| FastAPI application | VKM2 container | Device Event contract, domain rules, authorization, audit, UI, and APIs |
| SQLite database | Persistent VKM2 container volume | VKM2 operational data |
| Hardware client | Raspberry Pi host systemd service | RC522 and GPIO access, normalization, queuing, and delivery |

The hardware client will send events over loopback to VKM2's existing local
Device Event API. It will not use a public tunnel merely to reach an API on the
same Raspberry Pi.

The initial event mapping is:

| Physical input | VKM2 Device Event meaning |
| --- | --- |
| RFID credential read | `RFID_CREDENTIAL_READ` with an opaque credential reference |
| BCM17 changes to LOW | `KEY_ATTACHED` |
| BCM17 changes to HIGH | `KEY_REMOVED` |

The exact request schema, device identity, and authentication mechanism must
reuse the VKM2 Device Event contract and must be confirmed before deployment.

### 7.2 Required hardware-client behavior

The VKM2 hardware client must include:

1. **Stable event identifiers** so the server can process retries
   idempotently.
2. **Boot generation and monotonic sequence information** so event ordering
   and client restarts can be distinguished safely.
3. **A durable local outbox** written before delivery, with removal only after
   the server confirms acceptance.
4. **API readiness checks** before normal event delivery begins.
5. **Debounce and confirmation** appropriate for the reed switch, preserving
   the verified polarity while improving on the V1 two-sample limitation.
6. **Repeat suppression** that does not discard a legitimate transition.
7. **Startup reconciliation** that compares current physical state with the
   state known by VKM2 through an approved Device Event workflow.
8. **Retry with bounded backoff** when the local API is unavailable.
9. **Single-instance enforcement** to prevent two clients from reporting the
   same hardware simultaneously.
10. **Secret-safe logging** that never prints credential values, card IDs,
    authentication secrets, or sensitive request bodies.

The host systemd unit must start only after the required local interfaces are
available, restart after failure, and avoid a tight restart loop. Service
hardening and device permissions must be defined and reviewed before the unit
is enabled.

### 7.3 Business workflow boundary

For the first VKM2 operational pilot:

- RFID and key state drive the custody workflow automatically;
- Vehicle Use details are entered manually after key return;
- the physical pilot may use one hook, while configuration and contracts must
  remain extensible to additional hooks;
- a pending key-removal decision must be finalized by an explicit, tested
  runtime path rather than relying only on a test helper; and
- failures must be visible to operators and auditable.

## 8. Data migration policy

The V1 database and user mapping are evidence-bearing legacy data, not VKM2
installation inputs.

- Do not copy the V1 SQLite database into the VKM2 volume.
- Do not copy the V1 user mapping file into the VKM2 runtime.
- Do not publish legacy identifiers in source control.
- Register VKM2 identities, devices, hooks, keys, and vehicles through an
  approved management workflow with audit records.
- Preserve V1 data separately under an approved retention and access policy if
  it must remain available for historical reference.

Any later data conversion requires its own mapping specification, privacy
review, backup, validation, and Human Gate.

## 9. Verified results and open items

### 9.1 Verified PASS items

- RC522 initialization and physical card detection.
- SPI communication with the existing reader and wiring.
- BCM17 input behavior with the reed switch.
- Key attached as LOW and key removed as HIGH.
- FastAPI systemd startup and application readiness.
- A successful V1 status response.

### 9.2 Not yet verified

- final RC522 terminal-to-physical-pin wiring documentation;
- simultaneous RC522 and reed-switch operation;
- the final historical sensor startup order;
- VKM2 RFID Device Event processing with the real reader;
- VKM2 key-attached and key-removed Device Event processing;
- durable retry and recovery after API or network failure;
- startup reconciliation after a client or Pi restart;
- prevention and detection of duplicate sensor clients;
- end-to-end custody and Vehicle Use workflow;
- long-duration hardware stability; and
- automatic recovery of the complete VKM2 hardware integration after a Pi
  restart.

## 10. Human Gate sequence

Implementation and deployment should proceed through explicit approval gates:

1. Review the Device Event mapping, local authentication, outbox format,
   service hardening, and failure behavior.
2. Implement and test the host hardware client without changing the live Pi.
3. Register non-production test inventory through the VKM2 management path.
4. Deploy the client to the Pi without running the V1 and VKM2 monitors at the
   same time.
5. Run controlled RFID, key removal, key return, retry, duplicate, restart,
   audit, and Vehicle Use tests.
6. Enable operational use only after the evidence is reviewed and accepted.

No step in this document authorizes a Pi change, production event, database
restore, user-data migration, public exposure change, or credential operation.
