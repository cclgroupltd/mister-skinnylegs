import json
import re

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


BALANCES_PATTERN = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=SendReceivePreloadable")
USER_DETAILS_PATTERN = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=userQuery")
PAYMENT_METHODS_PATTERN = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=usePaymentMethodsQuery")
TRANSACTION_PATTERNS = [
        re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=AssetPagePortfolioWalletQuery"),
        re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=AccountActivityRedesignedQuery")
    ]


def get_coinbase_paymentmethods(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results_dups = []
    results = []

    for cache_rec in profile.iterate_cache(url=PAYMENT_METHODS_PATTERN):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data", {})
        viewer = data.get("viewer", {})
        payment_methods = viewer.get("paymentMethodsV2", [])

        if not payment_methods:
            log_func("No payment methods identified")

        for entry in payment_methods:
            result = { 
                "UUID": entry.get('uuid'),
                "Type": entry.get('type'),
                "Name": entry.get('name'),
                "Currency": entry.get('currency'),
                "Primary Buy Enabled": entry.get('primaryBuy'),
                "Primary Sell Enabled": entry.get('primarySell'),
                "Instant Buy Enabled": entry.get('instantBuy'),
                "Instant Sell Enabled": entry.get('instantSell'),
                "Created At": entry.get('createdAt'),
                "Updated At": entry.get('updatedAt'),
                "Verified": entry.get('verified'),
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }
            results_dups.append(result)
                
        for items in results_dups:
            if items not in results:
                results.append(items)

    return ArtifactResult(results)


def get_coinbase_userdetails(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for cache_rec in profile.iterate_cache(url=USER_DETAILS_PATTERN):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data", {})
        viewer = data.get("viewer", {})
        user_properties = viewer.get("userProperties") # should always exist since user information is a requirement to use the coinbase website.
        email = user_properties.get('email')
        personal_details = user_properties.get("personalDetails")
        legal_names = personal_details.get("legalName")
        address = personal_details.get('address')
        country = address.get('country')
        dob = personal_details.get('dateOfBirth')
        address_full = address['line1'], address['line2'], address['city'], address['postalCode'], country['code']

        result = { 
            "First Name": legal_names['firstName'],
            "Last Name": legal_names['lastName'],
            "Email": email,
            "Date of Birth": dob,
            "Address": " ".join(address_full),
            "Source": "Cache",
            "Data Location": str(cache_rec.data_location)
        }

        results.append(result)

    return ArtifactResult(results)


def get_coinbase_balances(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results_dups = []
    results = []

    for cache_rec in profile.iterate_cache(url=BALANCES_PATTERN):
        
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data")
        viewer = data.get("viewer")
        
        receive_accounts = viewer.get('receiveAccounts', [])
        if not receive_accounts:
            log_func("No receive accounts identified.")

        send_accounts = viewer.get('sendAccounts', [])
        if not send_accounts:
            log_func("No send accounts identified")

        for item in receive_accounts:
            available_balance = item['availableBalance']
            asset_or_fiat = item['assetOrFiatCurrency']
            asset = asset_or_fiat['asset']

            result = {
                "Type": item['type'],
                "Currency": available_balance['currency'],
                "Name": asset['name'],
                "Balance": available_balance['value'],
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }

            results_dups.append(result)

        for item in send_accounts:
            available_balance = item['availableBalance']
            asset_or_fiat = item['assetOrFiatCurrency']
            asset = asset_or_fiat['asset']

            result = {
                "Type": item['type'],
                "Currency": available_balance['currency'],
                "Name": asset['name'],
                "Balance": available_balance['value'],
                "Data Location": str(cache_rec.data_location)
            }
            
            results_dups.append(result)

        for items in results_dups:
            if items not in results:  # slow but ultimately fine
                results.append(items)

    return ArtifactResult(results)


def get_coinbase_transactions(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for url_pattern in TRANSACTION_PATTERNS:
        for cache_rec in profile.iterate_cache(url=url_pattern):
            cache_data = json.loads(cache_rec.data.decode("utf-8"))

            data = cache_data.get("data")
            viewer = data.get("viewer")
            account_by_uuid = viewer.get("accountByUuidV2")
            account_history_entries = account_by_uuid.get("accountHistoryEntries")
            edges = account_history_entries.get('edges', [])

            for edge in edges:
                node = edge.get('node')

                created_at = node.get("createdAt")
                title = node.get('title')
                amount = node.get('amount')
                currency = amount.get('currency')
                value = amount.get('value')
                category = node.get('category')

                details = node.get('details')
                if details:
                    send_recipent = details.get('cryptoSendRecipient')
                    transaction_url = details.get('transactionUrl')
                    payment_methods = details.get('paymentMethod')
                    withdraw_to = details.get('to')
                    desposit_from = details.get('from')

                if category == 'CRYPTO_SEND':
                    address = send_recipent['address']
                    transaction_url = transaction_url
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")


                elif category == 'CRYPTO_RECEIVE':
                    address = str('Unknown')
                    transaction_url = transaction_url
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")
                    
                elif category == 'BUY':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = payment_methods
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")

                elif category == 'SELL':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = payment_methods
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")

                elif category == 'FIAT_WITHDRAWAL':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = str('N/A')
                    withdraw_to = withdraw_to
                    desposit_from = str("N/A")

                elif category == 'FIAT_DEPOSIT':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = desposit_from

                elif category == 'UNSTAKING':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")

                elif category == 'STAKING':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")

                elif category == 'INTEREST':
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")

                elif category == "CONVERT":
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = payment_methods
                    withdraw_to = str("N/A")
                    desposit_from = str("N/A")

                elif category == "USER_RECEIVE":
                    address = str('N/A')
                    transaction_url = str('N/A')
                    payment_methods = str('N/A')
                    withdraw_to = str("N/A")
                    desposit_from = desposit_from

                else:
                    log_func("ERROR - Unknown transaction category identified.")
                    address = None
                    transaction_url = None
                    payment_methods = None
                    withdraw_to = None
                    desposit_from = None

                result = {
                    "Created Date/Time": str(created_at),
                    "Category": str(category),
                    "Type": str(title),
                    "Currency": str(currency),
                    "Value": str(value),
                    "Address": str(address),
                    "Transaction URL": str(transaction_url),
                    "Payment Method": str(payment_methods),
                    "Withdraw To": str(withdraw_to),
                    "Deposit From": str(desposit_from),
                    "Source": "Cache",
                    "Data Location": str(cache_rec.data_location)
                }
                results.append(result)

    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Coinbase",
        "Coinbase Payment Methods",
        "Recovers Coinbase Payement Methods records from the Cache",
        "0.1",
        get_coinbase_paymentmethods,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Coinbase",
        "Coinbase User Details",
        "Recovers Coinbase User Details records from the Cache",
        "0.1",
        get_coinbase_userdetails,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Coinbase",
        "Coinbase Balances",
        "Recovers Coinbase Balances records from the Cache",
        "0.1",
        get_coinbase_balances,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Coinbase",
        "Coinbase Transactions",
        "Recovers Coinbase Transactions from the Cache",
        "0.1",
        get_coinbase_transactions,
        ReportPresentation.table
    ),
)
