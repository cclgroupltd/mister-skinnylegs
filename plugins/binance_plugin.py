import json
import re

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


BALANCES_PATTERN = re.compile(r"binance.*?\.[A-z]{2,3}/bapi/asset/v2/private/asset-service/wallet/balance")
USER_DETAILS_PATTERN = re.compile(r"binance.*?\.[A-z]{2,3}/bapi/fiat/v3/private/cards/get-user-info")


def get_binance_userdetails(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    
    for cache_rec in profile.iterate_cache(url=USER_DETAILS_PATTERN):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data", {})
        address_full = data['billingAddr1'], data['billingCity'], data['billingState'], data['billingPostalCode']

        result = { 
            "First Name": data['firstName'],
            "Last Name": data['lastName'],
            "Address": " ".join(address_full),
            "Source": "Cache",
            "Data Location": str(cache_rec.data_location)
        }

        results.append(result)

    return ArtifactResult(results)


def get_binance_balances(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for cache_rec in profile.iterate_cache(url=BALANCES_PATTERN):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))

        data = cache_data.get('data')

        for item in data:
            account_type = item.get('accountType')
            wallet_name = item.get('walletName')
            asset_balances = item.get('assetBalances', {})

            for item in asset_balances:
                asset = item.get('asset')
                asset_name = item.get('assetName')
                free_balance = item.get('free')
                locked_balance = item.get('locked')
                frozen_balance = item.get('freeze')

                result = { 
                    "Account Type": account_type,
                    "Wallet Name": wallet_name,
                    "Asset": asset,
                    "Asset Name": asset_name,
                    "Free Balance": free_balance,
                    "Locked Balance": locked_balance,
                    "Frozen Balance": frozen_balance,
                    "Source": "Cache",
                    "Data Location": str(cache_rec.data_location)
                }

                results.append(result)

    return ArtifactResult(results)

__artifacts__ = (
    ArtifactSpec(
        "Binance",
        "Binance User Details",
        "Recovers Binance User Details records from the Cache",
        "0.1",
        get_binance_userdetails,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Binance",
        "Binance Balances",
        "Recovers Coinbase Balances records from the Cache",
        "0.1",
        get_binance_balances,
        ReportPresentation.table
    ),
)
