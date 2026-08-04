#!/usr/bin/env bash
set -euo pipefail

# Required inputs keep SSH exposure and key selection explicit.
: "${PTCG_AZURE_SSH_SOURCE:?Set to your public IP in CIDR form, e.g. 203.0.113.4/32}"
: "${PTCG_AZURE_SSH_KEY:?Set to the path of your SSH public key}"

PTCG_LOCATION="${PTCG_AZURE_LOCATION:-eastus}"
PTCG_GROUP="${PTCG_AZURE_GROUP:-ptcg-ai-rg}"
PTCG_VM="${PTCG_AZURE_VM:-ptcg-train}"
PTCG_SIZE="${PTCG_AZURE_SIZE:-Standard_D16ds_v5}"
PTCG_PRIORITY="${PTCG_AZURE_PRIORITY:-Spot}"
PTCG_NSG="${PTCG_VM}-nsg"

case "$PTCG_PRIORITY" in
  Spot)
    PTCG_PRIORITY_ARGS=(--priority Spot --eviction-policy Delete --max-price -1)
    ;;
  Regular)
    PTCG_PRIORITY_ARGS=(--priority Regular)
    ;;
  *)
    echo "PTCG_AZURE_PRIORITY must be Spot or Regular" >&2
    exit 2
    ;;
esac

az account show --output none
az group create --name "$PTCG_GROUP" --location "$PTCG_LOCATION" --output none
az network nsg create --resource-group "$PTCG_GROUP" --name "$PTCG_NSG" --location "$PTCG_LOCATION" --output none
az network nsg rule create \
  --resource-group "$PTCG_GROUP" \
  --nsg-name "$PTCG_NSG" \
  --name ssh-from-owner \
  --priority 100 \
  --access Allow \
  --protocol Tcp \
  --direction Inbound \
  --source-address-prefixes "$PTCG_AZURE_SSH_SOURCE" \
  --destination-port-ranges 22 \
  --output none
az vm create \
  --resource-group "$PTCG_GROUP" \
  --name "$PTCG_VM" \
  --location "$PTCG_LOCATION" \
  --image Ubuntu2204 \
  --size "$PTCG_SIZE" \
  "${PTCG_PRIORITY_ARGS[@]}" \
  --admin-username azureuser \
  --ssh-key-values "$PTCG_AZURE_SSH_KEY" \
  --nsg "$PTCG_NSG" \
  --custom-data infra/cloud-init.yaml \
  --os-disk-size-gb 64 \
  --public-ip-sku Standard \
  --output table
az vm auto-shutdown \
  --resource-group "$PTCG_GROUP" \
  --name "$PTCG_VM" \
  --time 0500 \
  --output none

echo "VM provisioned. Retrieve its IP with:"
echo "az vm show -d -g $PTCG_GROUP -n $PTCG_VM --query publicIps -o tsv"
