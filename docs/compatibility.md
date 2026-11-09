# Compatibility and known limitations

## Qualified host boundary

The Desktop backend is currently tied to Hermes source revision
`109fd8161a509db5a00942152ba48882e446e8b0`, or the exact compatible managed-runtime
API bytes listed in [host-lock.json](../studio/host-lock.json). Other host builds
fail closed. A version lower bound alone does not establish compatibility.

The source uses the public plugin registration and Desktop SDK surfaces, but
some backend paths also import non-public Hermes owner/session, approval,
sensitive-route and project-registry helpers. These imports are disclosed
maintenance and catalog-review risks. Do not remove security checks merely to
silence an admission warning.

## Execution

Native owned media execution is Linux-focused. Windows/macOS backend execution,
arbitrary host upgrades and every render/export combination are not claimed
qualified. Local rendering depends on the discovered executables and actual
resource/GPU admission. Optional engines, codecs, fonts and models have
independent availability.

## Loaded client identity

Cross-client loaded-code parity and save persistence remain unqualified. An
observed Windows client/backend build mismatch blocks saving despite matching
files on disk. Matching filesystem bytes do not prove the frontend and backend
loaded the same build. Keep the mismatch guard; resolve it through the host's
supported, explicitly authorized lifecycle before claiming client acceptance.

## Release status

This is an early public source preview. Catalog validation is distinct from
maintainer acceptance; targeted source tests are distinct from installed
end-to-end rendering or creative acceptance. Private production evidence is
not part of this distribution. Check the final verification record rather than
assuming unrun routes passed.

## Updating

This public distribution has no automatic self-updater. Use the host's supported
plugin update/install flow with an explicitly selected reviewed commit.
Private operator deployment and synchronization helpers are not shipped.

## Broader acceptance status

The original development aggregate is not fully green. Legacy integration
fixtures and a downstream Breeze journey remain under investigation. This source
preview does not claim that all production journeys or render/export routes
have passed. The public focused suite and official plugin validation are
reported separately.
