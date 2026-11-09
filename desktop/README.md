# Motion Studio Desktop

This package registers its interface through the Hermes Desktop plugin SDK.
The backend validates host compatibility, owner/session context and immutable
request bindings before executing supported operations.

Install through the native Hermes plugin lifecycle. Do not copy JavaScript into
app internals, inject scripts or bypass the SDK loader. After updating, use the
host's supported reload or a fresh session and verify the loaded build identity.

See [usage](../docs/hermes.md) and [compatibility](../docs/compatibility.md).
