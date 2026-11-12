#!/usr/bin/env bash
# Fetch the ASAP7 7.5-track NLDM liberty files, all four Vt flavours,
# from the OpenROAD-flow-scripts repository into libs/asap7/.
#
#   flow/get_asap7.sh                        TT and SS corners
#   CORNERS="TT SS FF" flow/get_asap7.sh     add the FF corner
#   REF=<commit-sha> flow/get_asap7.sh       pin to a specific upstream commit
set -euo pipefail

REPO=The-OpenROAD-Project/OpenROAD-flow-scripts
REF=${REF:-master}
CORNERS=${CORNERS:-"TT SS"}
DEST="$(cd "$(dirname "$0")/.." && pwd)/libs/asap7"
BASE="https://raw.githubusercontent.com/$REPO/$REF/flow/platforms/asap7/lib/NLDM"

mkdir -p "$DEST"

for corner in $CORNERS; do
  for vt in SRAM RVT LVT SLVT; do
    files=(
      "asap7sc7p5t_AO_${vt}_${corner}_nldm_211120.lib.gz"
      "asap7sc7p5t_OA_${vt}_${corner}_nldm_211120.lib.gz"
      "asap7sc7p5t_SIMPLE_${vt}_${corner}_nldm_211120.lib.gz"
      "asap7sc7p5t_INVBUF_${vt}_${corner}_nldm_220122.lib.gz"
      "asap7sc7p5t_SEQ_${vt}_${corner}_nldm_220123.lib"
    )
    # Upstream replaced this one file; its 211120 version is a 44-byte stub.
    if [[ $vt == RVT && $corner == FF ]]; then
      files[2]="asap7sc7p5t_SIMPLE_RVT_FF_nldm_250407.lib.gz"
    fi

    for f in "${files[@]}"; do
      out="$DEST/${f%.gz}"
      if [[ -s $out ]]; then
        continue                      # already fetched
      fi
      echo "fetching $f"
      curl -fsSL --retry 3 -o "$DEST/$f" "$BASE/$f"
      if [[ $f == *.gz ]]; then
        gunzip -f "$DEST/$f"
      fi
    done
  done
done

# Record where the files came from, so results can be reproduced.
sha=$(git ls-remote "https://github.com/$REPO" "$REF" | cut -f1 | head -n1)
{
  echo "repo:   $REPO"
  echo "ref:    $REF"
  echo "commit: ${sha:-$REF}"
  echo "date:   $(date -u +%F)"
} > "$DEST/SOURCE.txt"
(cd "$DEST" && sha256sum *.lib > SHA256SUMS)

echo "done: $(ls "$DEST"/*.lib | wc -l) liberty files in $DEST"
