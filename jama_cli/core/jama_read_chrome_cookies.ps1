# Jama cookie decryption helper (Windows side of `jama login --from-browser chrome|edge`).
#
# Runs on the Windows host, AS THE USER, so it can use the OS's own key material
# (DPAPI, and for App-Bound Encryption the per-user COM service) to decrypt the
# browser's cookie values. This is the mechanism Chromium itself uses to read the
# current user's cookies; it cannot read another user's.
#
# Contract (kept stable; the Python side mocks it in tests):
#   stdin : one line of JSON { "encrypted_key": "<base64>",
#                              "cookies": { "<name>": "<base64 encrypted_value>", ... } }
#   stdout: one line of JSON { "<name>": "<plaintext value>", ... }  on success
#   exit  : non-zero with a short reason on stderr on failure
#
# It never prints the key or anything but the two requested values. It touches no
# files. App-Bound (v20) blobs are not unwrapped here; the helper reports that
# clearly so the CLI can tell the user to use Firefox or `jama login` instead.

$ErrorActionPreference = "Stop"

function Fail($msg) { [Console]::Error.WriteLine($msg); exit 1 }

try {
    Add-Type -AssemblyName System.Security | Out-Null
    $raw = [Console]::In.ReadToEnd()
    if (-not $raw) { Fail "no input" }
    $req = $raw | ConvertFrom-Json

    # 1. Unwrap the AES key: base64 -> strip the 5-byte "DPAPI" prefix -> DPAPI.
    $wrapped = [Convert]::FromBase64String($req.encrypted_key)
    if ($wrapped.Length -le 5) { Fail "encryption key too short" }
    $dpapi = New-Object byte[] ($wrapped.Length - 5)
    [Array]::Copy($wrapped, 5, $dpapi, 0, $wrapped.Length - 5)
    $key = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $dpapi, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)

    $aesGcm = $null
    try { $aesGcm = [System.Security.Cryptography.AesGcm] } catch { $aesGcm = $null }

    $out = @{}
    foreach ($name in $req.cookies.PSObject.Properties.Name) {
        $blob = [Convert]::FromBase64String($req.cookies.$name)
        if ($blob.Length -lt 3) { Fail "cookie '$name' is empty" }
        $prefix = [System.Text.Encoding]::ASCII.GetString($blob, 0, 3)

        if ($prefix -eq "v20") {
            Fail ("cookie '$name' uses App-Bound Encryption (v20); not supported by this helper")
        }
        if ($prefix -ne "v10") {
            Fail "cookie '$name' has an unexpected format"
        }
        if ($null -eq $aesGcm) {
            Fail "AES-GCM needs PowerShell 7 (pwsh); Windows PowerShell 5 cannot decrypt v10"
        }

        # v10 layout: "v10" | nonce(12) | ciphertext | tag(16)
        $nonce = New-Object byte[] 12
        $tag = New-Object byte[] 16
        $ctLen = $blob.Length - 3 - 12 - 16
        if ($ctLen -lt 0) { Fail "cookie '$name' is truncated" }
        $cipher = New-Object byte[] $ctLen
        [Array]::Copy($blob, 3, $nonce, 0, 12)
        [Array]::Copy($blob, 15, $cipher, 0, $ctLen)
        [Array]::Copy($blob, 15 + $ctLen, $tag, 0, 16)

        $plain = New-Object byte[] $ctLen
        $gcm = [System.Security.Cryptography.AesGcm]::new($key)
        try { $gcm.Decrypt($nonce, $cipher, $tag, $plain) } finally { $gcm.Dispose() }

        # Chrome (M104+) prepends a 32-byte domain hash before encrypting; drop it
        # when what remains is valid text, else keep the whole plaintext.
        $value = $null
        if ($plain.Length -gt 32) {
            try {
                $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
                $value = $utf8.GetString($plain, 32, $plain.Length - 32)
            } catch { $value = $null }
        }
        if ($null -eq $value) {
            $value = [System.Text.Encoding]::UTF8.GetString($plain)
        }
        $out[$name] = $value
    }

    [Console]::Out.WriteLine(($out | ConvertTo-Json -Compress))
    exit 0
}
catch {
    Fail ($_.Exception.Message)
}
