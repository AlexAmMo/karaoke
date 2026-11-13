#!/bin/bash
# Install a published release into ~/Applications; preserve all application data.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo 'Este instalador es para macOS.' >&2; exit 1; }
repo=AlexAmMo/karaoke
arch="$(uname -m)"
case "$arch" in arm64|x86_64) ;; *) echo "Arquitectura no disponible: $arch" >&2; exit 1;; esac
version="${KARAOKE_VERSION:-latest}"
if [[ "$version" == latest ]]; then
  tag="$(curl --fail --silent --show-error --location "https://api.github.com/repos/$repo/releases/latest" | /usr/bin/plutil -extract tag_name raw -o - -)" || { echo 'Todavía no hay una versión estable publicada. Consulta Releases en GitHub.' >&2; exit 1; }
else
  [[ "$version" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([.-][a-zA-Z0-9.-]+)?$ ]] || { echo 'Versión no válida.' >&2; exit 1; }
  tag="$version"
fi
number="${tag#v}"
asset="Karaoke-$number-macos-$arch.zip"
base="https://github.com/$repo/releases/download/$tag"
work="$(mktemp -d -t karaoke-install)"
trap 'rm -rf "$work"' EXIT
curl --fail --show-error --location "$base/$asset" -o "$work/$asset"
curl --fail --show-error --location "$base/$asset.sha256" -o "$work/$asset.sha256"
expected="$(awk 'NR==1 { print $1 }' "$work/$asset.sha256")"
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || { echo 'El archivo de verificación no es válido.' >&2; exit 1; }
actual="$(shasum -a 256 "$work/$asset" | awk '{print $1}')"
[[ "$actual" == "$expected" ]] || { echo 'La descarga no supera la verificación SHA-256.' >&2; exit 1; }
/usr/bin/ditto -x -k "$work/$asset" "$work/extracted"
app="$work/extracted/Karaoke.app"
[[ -x "$app/Contents/MacOS/karaoke" ]] || { echo 'El paquete está incompleto.' >&2; exit 1; }
/usr/bin/codesign --verify --deep --strict "$app"
minimum="$(/usr/bin/plutil -extract LSMinimumSystemVersion raw -o - "$app/Contents/Info.plist")"
current="$(sw_vers -productVersion)"
# Compare dotted numeric versions without requiring Python/Homebrew.
if ! awk -v current="$current" -v minimum="$minimum" 'BEGIN {split(current,a,"."); split(minimum,b,"."); for(i=1;i<=3;i++){if(a[i]+0>b[i]+0)exit 0; if(a[i]+0<b[i]+0)exit 1} exit 0}'; then
  echo "Este paquete requiere macOS $minimum; tienes $current." >&2; exit 1
fi
mkdir -p "$HOME/Applications"
target="$HOME/Applications/Karaoke.app"
backup="$HOME/Applications/Karaoke.previous.app"
if pgrep -f "$target/Contents/MacOS/karaoke" >/dev/null; then
  echo 'Cierra Karaoke antes de actualizar.' >&2; exit 1
fi
[[ ! -e "$backup" ]] || { echo "Existe una copia de actualización anterior en $backup. Revísala antes de continuar." >&2; exit 1; }
if [[ -e "$target" ]]; then mv "$target" "$backup"; fi
if ! mv "$app" "$target"; then
  if [[ -e "$backup" ]]; then mv "$backup" "$target"; fi
  exit 1
fi
if [[ -e "$backup" ]]; then rm -rf "$backup"; fi
echo "Karaoke instalado en $target"
echo 'La biblioteca y la configuración se conservan en Application Support/Karaoke.'
echo 'Abre Karaoke desde Finder. Una compilación sin notarizar puede requerir autorización en Ajustes del Sistema.'
