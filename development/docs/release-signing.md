# Release signing

The device checks each downloaded release, software or firmware, against a
detached OpenPGP signature before preparing it (checklist U2). It runs
`gpgv` with the release keyring shipped in the app. This page covers what the
cloud must serve, how to make and keep the key, and when to make the check
strict.

Until the cloud serves signatures and the keyring is installed, every release
reads as unsigned. In the default `warn` mode, the device shows a warning and
installs as before.

## On the device

- **Keyring:** `runtime/raspberry-pi/main/config/release-keyring.gpg`, a
  binary keyring holding the release public key or keys. It is not in the
  repository yet: the owner supplies the key.
  - The device always checks against the keyring it already has installed,
    never one inside a download.
  - Keyring changes therefore arrive in a release, which is itself checked
    against the keys the device already trusts.
- **Setting:** `KNEESPA_RELEASE_SIGNATURE_MODE` in the device `.env`.

  | Mode | Missing or bad signature |
  | --- | --- |
  | `warn` (default) | Logged, shown on the release screen and in the install prompt; the install continues. |
  | `enforce` | The install is refused. Nothing is prepared or installed. |

  Any other value counts as `enforce`, so a typo never weakens the check.
- **Results:**
  - *valid*: `gpgv` accepts the signature with a key from the keyring;
  - *invalid*: `gpgv` rejects it;
  - *missing*: the cloud has no signature for the release, or it could not be
    downloaded;
  - *unsigned*: the device cannot check, because `gpgv` or the keyring is
    absent.
- **Dependency:** `gpgv` comes with `apt` on Raspberry Pi OS, so nothing needs
  installing. On Windows development machines the check reads as unsigned.

## What the cloud must serve

- **Endpoint:** `GET /api/v1/admin/releases/{id}/signature`, next to the
  release's `/download`, with the same staff session and permission
  (`devices.view`). It must not redirect, because the device refuses
  redirects.
- **Body:** the detached signature of the exact bytes `/download` returns.
  - Binary (`gpg --detach-sign`) or ASCII-armoured (`--armor`) both work.
  - It must be under 64 KiB.
- **Content type:** `application/pgp-signature`, or
  `application/octet-stream`.
- **No signature:** answer `404`. The device then reports the release as
  missing a signature.
- **Order:** the signature must exist before the release is offered as
  `latest`. Otherwise devices in `enforce` mode refuse it.

## The signing key

- **Generate it once, offline**, on a machine that never runs the cloud
  service:

  ```bash
  gpg --quick-generate-key "KneeSpa releases <releases@your-domain>" ed25519 sign 3y
  ```

  Choose a passphrase. Record the fingerprint (`gpg --list-keys --with-fingerprint`).
- **Export the public keyring for the app** in binary form, because `gpgv`
  does not read armoured keyrings:

  ```bash
  gpg --export <FINGERPRINT> > runtime/raspberry-pi/main/config/release-keyring.gpg
  ```

  Commit that file, so that it ships with the next release.
- **Store the private key** offline, with an encrypted backup in a second
  place:

  ```bash
  gpg --export-secret-keys --armor <FINGERPRINT> > release-signing-key.asc
  ```

  Never give it to the cloud service. The cloud stores and serves signatures;
  it never makes them.
- **Sign each release** as part of uploading it. Sign the exact file being
  uploaded:

  ```bash
  gpg --local-user <FINGERPRINT> --detach-sign --output <file>.sig <file>
  ```

  Check the signature before uploading it:

  ```bash
  gpgv --keyring runtime/raspberry-pi/main/config/release-keyring.gpg <file>.sig <file>
  ```
- **Rotate** before the key expires, or at once if it is compromised:
  1. Generate the new key.
  2. Ship a release signed with the old key whose keyring holds both keys.
     Devices trust it because they already hold the old key.
  3. Once every device runs that release, sign with the new key only.
  4. Ship a later release whose keyring drops the old key.
  - If the old key is compromised, a device cannot tell a forged "rotation"
    release from a real one. Install the new keyring by hand (routine sync
    of `runtime/`), and switch those devices to `enforce` only afterwards.

## When to switch to `enforce`

Switch a device's `.env` to `KNEESPA_RELEASE_SIGNATURE_MODE=enforce` only when
all of these hold:

1. **The device has the keyring:** a release containing
   `release-keyring.gpg` is installed on it.
2. **The cloud serves a valid signature** for every release it offers.
3. **One warn-mode update has gone through** on that device with no
   signature warning on the release screen.

Until then, `enforce` would refuse every update.
