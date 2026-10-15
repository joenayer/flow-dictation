#!/usr/bin/env bash
# Explicit admin operation: generate/retain a private preview key and provision
# repository Actions secrets. Never invoked by CI or the ordinary build.
set -euo pipefail
umask 077
if [ "$#" -ne 2 ]; then
  echo 'Usage: setup-preview-signing.sh OWNER/REPO PRIVATE_BACKUP_DIRECTORY' >&2
  exit 2
fi
repo="$1"
private_dir="$2"
for tool in gh keytool openssl base64 realpath; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
project_root="$(cd "$(dirname "$0")/../.." && pwd -P)"
private_dir="$(realpath -m "$private_dir")"
case "$private_dir/" in
  "$project_root/"*) echo 'Choose a private backup directory outside the repository.' >&2; exit 1 ;;
esac
# Check access before generating any key. A readable public-key endpoint is
# necessary but does not guarantee that later secret writes are authorized.
gh api "repos/$repo/actions/secrets/public-key" >/dev/null
preflight_error="$(mktemp)"
trap 'rm -f "$preflight_error"' EXIT
remote_cert=''
if remote_cert="$(gh api "repos/$repo/actions/variables/FLOW_PREVIEW_CERT_SHA256" --jq .value 2>"$preflight_error")"; then
  remote_cert="$(printf '%s' "$remote_cert" | tr '[:upper:]' '[:lower:]')"
  printf '%s' "$remote_cert" | grep -Eq '^[a-f0-9]{64}$' || {
    echo 'Remote certificate pin is invalid; refusing signing changes.' >&2; exit 1;
  }
elif grep -Fq '(HTTP 404)' "$preflight_error"; then
  # Public-key access has already established that this repository exists.
  # Only an explicit missing-variable response permits initial setup.
  remote_cert=''
else
  cat "$preflight_error" >&2
  echo 'Cannot determine the established certificate; refusing signing changes.' >&2
  exit 1
fi
remote_secrets="$(gh api --paginate "repos/$repo/actions/secrets" --jq '.secrets[].name')"
if [ ! -f "$private_dir/preview.jks" ]; then
  if [ -n "$remote_cert" ] || printf '%s\n' "$remote_secrets" | grep -Eq '^FLOW_PREVIEW_(KEYSTORE_BASE64|STORE_PASSWORD|KEY_ALIAS|KEY_PASSWORD)$'; then
    echo 'Preview signing is already established or partially configured. Use its existing private backup; refusing a new key.' >&2
    exit 1
  fi
fi
if [ ! -d "$private_dir" ]; then
  mkdir -m 700 -p "$private_dir"
fi
chmod 700 "$private_dir"
if [ ! -f "$private_dir/preview.jks" ]; then
  if [ -n "$(ls -A "$private_dir")" ]; then
    echo 'Refusing to generate into a nonempty directory without its preview key.' >&2
    exit 1
  fi
  openssl rand -hex 32 > "$private_dir/store-password"
  openssl rand -hex 32 > "$private_dir/key-password"
  printf '%s\n' "$repo" > "$private_dir/repository"
  export FLOW_SETUP_STORE_PASSWORD="$(cat "$private_dir/store-password")"
  export FLOW_SETUP_KEY_PASSWORD="$(cat "$private_dir/key-password")"
  keytool -genkeypair -keystore "$private_dir/preview.jks" -storetype JKS \
    -alias flow-preview -keyalg RSA -keysize 3072 -validity 10000 \
    -dname 'CN=Flow Preview' -storepass:env FLOW_SETUP_STORE_PASSWORD \
    -keypass:env FLOW_SETUP_KEY_PASSWORD >/dev/null 2>&1
else
  test "$(cat "$private_dir/repository")" = "$repo" || {
    echo 'This key backup belongs to another repository.' >&2; exit 1;
  }
  export FLOW_SETUP_STORE_PASSWORD="$(cat "$private_dir/store-password")"
  export FLOW_SETUP_KEY_PASSWORD="$(cat "$private_dir/key-password")"
fi
chmod 600 "$private_dir"/*
keytool -exportcert -keystore "$private_dir/preview.jks" -alias flow-preview \
  -storepass:env FLOW_SETUP_STORE_PASSWORD 2>/dev/null |
  openssl x509 -inform DER -noout -fingerprint -sha256 |
  sed 's/.*=//; s/://g' | tr '[:upper:]' '[:lower:]' > "$private_dir/certificate-sha256"
test "$(wc -c < "$private_dir/certificate-sha256")" -eq 65
if [ -n "$remote_cert" ] && [ "$(cat "$private_dir/certificate-sha256")" != "$remote_cert" ]; then
  echo 'Local key does not match the established remote certificate; refusing all secret writes.' >&2
  exit 1
fi
# gh handles encryption against the repository public key. Values are passed
# through stdin, never command arguments or output. A failed upload leaves the
# private backup intact, so rerunning provisions the SAME key.
base64 -w 0 "$private_dir/preview.jks" | gh secret set FLOW_PREVIEW_KEYSTORE_BASE64 --repo "$repo"
gh secret set FLOW_PREVIEW_STORE_PASSWORD --repo "$repo" < "$private_dir/store-password"
printf '%s' flow-preview | gh secret set FLOW_PREVIEW_KEY_ALIAS --repo "$repo"
gh secret set FLOW_PREVIEW_KEY_PASSWORD --repo "$repo" < "$private_dir/key-password"
gh variable set FLOW_PREVIEW_CERT_SHA256 --repo "$repo" < "$private_dir/certificate-sha256"
unset FLOW_SETUP_STORE_PASSWORD FLOW_SETUP_KEY_PASSWORD
echo 'Persistent preview signing configured. Keep the private backup and passwords securely.'
echo 'A new key cannot update an earlier APK signed with a different key.'
