# sas blues — fix notes

## First, figure out which problem you actually have

Distinguish between the encoding change being at the **export step only** vs. at the **session level** — this changes how worried you should be about data you've already exported.

`wlatin1` (Windows-1252/cp1252) covers Portuguese and Swedish characters (they fit within Latin-1), but it does **not** cover Polish diacritics (ą, ć, ę, ł, ń, ó, ś, ź, ż — those need Latin-2 or Unicode). If someone changed your SAS EG *session* encoding (not just the export destination's encoding), Polish addresses may already be getting silently mangled or replaced with `?`/boxes the moment SAS reads them from Oracle — and that's not fixable at export time, because the data is already lossy by the time it reaches the CSV step. If it's *only* the export/output encoding that changed, the source data in the SAS session is still intact, and you just need to force the write step back to UTF-8.

**Quick diagnostic:** after your `PROC SQL` step, does the result grid in SAS EG *display* Polish names correctly in the viewer, before you even export?
- Names look right in the grid → it's just the export step, easy fix (below).
- Names already look wrong in the grid itself → it's the session encoding, and the fix needs to happen upstream of export (session/connection config, possibly a different Citrix profile).

## Fix 1 — force UTF-8 on export regardless of session default

Bypasses the GUI's "right-click → export" (which follows whatever the session default now is). Either option below replaces the manual step.

```sas
/* Option A: ODS CSV destination, explicit encoding */
ods csv file="C:\your\output\path.csv" encoding="utf-8";
proc print data=x noobs; run;
ods csv close;
```

```sas
/* Option B: PROC EXPORT, but point it at a fileref with encoding set */
filename outcsv "C:\your\output\path.csv" encoding="utf-8";
proc export data=x outfile=outcsv dbms=csv replace;
run;
```

Either one ignores the session's default output encoding and writes UTF-8 no matter what someone changed in EG's settings.

## Fix 2 — write straight to your C-drive from the Citrix session, no manual export/download step

Depends entirely on whether Citrix **client drive mapping** is enabled for your session:

- If enabled, your local C-drive is usually reachable from inside the remote session as `\\tsclient\C\...` (classic Citrix) or a mapped drive letter (`V:\`, depends on policy).
- If so, point the `filename`/`ods csv file=` path at that instead of a path on the remote machine:

```sas
ods csv file="\\tsclient\C\your\output\path.csv" encoding="utf-8";
proc print data=x noobs; run;
ods csv close;
```

**Unverified** — no access to the actual Citrix environment to confirm whether client drive mapping is enabled or what the exact path prefix is; this is IT-policy-dependent. Worth checking with whoever administers the Citrix setup, or just trying `\\tsclient\C\` and seeing if SAS resolves it.

## Full script

Puts the connection + `PROC SQL` fragment from `sas_blues` together with fix 1 into one runnable-shaped script.

**UNTESTED** — written from documented SAS/ACCESS-to-Oracle and ODS CSV syntax, no SAS environment available in this session to run it in. Verify the connection block and paths against your real Citrix session before relying on it. `TODO` markers show what needs your real values.

```sas
/* ============================================================
   sas_export_utf8.sas

   Full pipeline: connect to Oracle -> PROC SQL -> export UTF-8 CSV,
   bypassing the manual right-click export (and whatever the session
   default encoding has been changed to).
   ============================================================ */

/* ---------- 1. connection ---------- */
/* SAS/ACCESS Interface to Oracle -- adjust path/schema to your
   actual TNS entry and schema name.

   Don't hardcode a plaintext password in a script you might save or
   share. Run this once, interactively, to get an encoded password:
       proc pwencode in="your_password";
       run;
   then paste the printed {sas001...} value below instead of plain
   text. */
%let ora_user = your_username;               /* TODO: your username */
%let ora_pass = {sas001...};                 /* TODO: PROC PWENCODE output, not plaintext */

libname oralib oracle
    path="your_tns_entry"                     /* TODO: your TNS/connect string */
    schema="your_schema"                      /* TODO: your Oracle schema */
    user="&ora_user"
    password="&ora_pass";

/* ---------- 2. the program ---------- */
proc sql;
    create table work.x as
    select a, b
    from oralib.z;                            /* TODO: your real table/columns */
quit;

/* ---------- 3. export, forced UTF-8 regardless of session default ---------- */
%let out_path = C:\your\output\path\x_export.csv;   /* TODO: real output path */

/* Citrix client-drive alternative, if client drive mapping is
   enabled for your session (unverified -- see fix 2 above):
%let out_path = \\tsclient\C\your\output\path\x_export.csv;
*/

ods csv file="&out_path" encoding="utf-8";
proc print data=work.x noobs;
run;
ods csv close;

/* ---------- 4. tidy up ---------- */
libname oralib clear;
```

## Fix 3 — skip CSV entirely, port via SAS's native `.sas7bdat` format

While the Oracle-connection authority issue is still unsorted: SAS Enterprise Guide's default "save"/export proposes its own native binary dataset format, `.sas7bdat`. It's directly readable from Python — no manual CSV export, no session-encoding-vs-CSV-encoding fight, because there's no text round-trip at all:

```python
import pandas as pd
df = pd.read_sas("export.sas7bdat", format="sas7bdat")
```

Caveats:
- `pandas.read_sas()`'s encoding auto-detection isn't always reliable — if characters come out garbled, pass `encoding="latin1"` or `"cp1252"` explicitly, or install `pyreadstat` (`pyreadstat.read_sas7bdat(path)`), which handles SAS's encoding metadata more robustly.
- This only avoids adding a *new* lossy step. If the root cause turns out to be session-level (not just the export default — see the open question below), Polish characters could still be mangled before the `.sas7bdat` file is even saved, same as with CSV.

See `sas7bdat_to_csv_utf8.py` (same directory) for a small wrapper that reads a `.sas7bdat` and writes a UTF-8 CSV in one step, useful for the initial porting push before a proper database/pipeline is in place.

## Open question

Which situation applies — grid already shows mangled Polish characters before export (session-level problem), or everything's readable there and it's purely the CSV step going sideways (export-level problem, fix 1 alone should cover it)?
