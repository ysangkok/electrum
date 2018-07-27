import asyncio
import logging
import tempfile
import os
import hashlib
import collections

from connectrum.client import StratumClient
from connectrum.svr_info import ServerInfo

from electrum.wallet import Wallet
from electrum.storage import WalletStorage
from electrum.bitcoin import address_to_scripthash
from electrum.constants import set_testnet, set_regtest
from electrum.keystore import from_xpub
from electrum.util import bh2u, PrintError
from electrum.transaction import Transaction

# big wallet on testnet
set_testnet()
vpub = "vpub5VfkVzoT7qgd5gUKjxgGE2oMJU4zKSktusfLx2NaQCTfSeeSY3S723qXKUZZaJzaF6YaF8nwQgbMTWx54Ugkf4NZvSxdzicENHoLJh96EKg"
conn = 'testnet.qtornado.com', 51001
# small wallet (regtest)
#set_regtest()
#vpub = "vpub5UqWay427dCjkpE3gPKLnkBUqDRoBed1328uNrLDoTyKo6HFSs9agfDMy1VXbVtcuBVRiAZQsPPsPdu1Ge8m8qvNZPyzJ4ecPsf6U1ieW4x"
#conn = 'localhost', 51001

wallet_file_handle, wallet_file = tempfile.mkstemp(prefix="connectrum-")
os.close(wallet_file_handle)
os.unlink(wallet_file)
storage = WalletStorage(wallet_file)
storage.put('keystore', from_xpub(vpub).dump())
storage.put('wallet_type', 'standard')
storage.put('use_encryption', False)
storage.write()

class MergingAsyncIterator:
    """
    Generic class implementing collections.abc.AsyncIterator

    __anext__ will give an element from either of the iterators within.

    New iterators can be added with also_yield_from()
    """
    def __init__(self, initial_iterator):
        assert isinstance(initial_iterator, collections.abc.AsyncIterator)
        self.gens = [initial_iterator]
        self.results = collections.deque()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return self.results.pop()
        except IndexError:
            pass
        done, pending = await asyncio.wait([x.__anext__() for x in self.gens], return_when=asyncio.FIRST_COMPLETED)
        for i in pending: i.cancel()
        self.results.extendleft(x.result() for x in done)
        return self.results.pop()

    def also_yield_from(self, new_iterator):
        assert isinstance(new_iterator, collections.abc.AsyncIterator)
        self.gens.append(new_iterator)

class NewNetwork(PrintError):
    def __init__(self, wallet):
        self.transactions = 0
        self.wallet = wallet
        self.new_addresses = set()
        self.requested_histories = {}
        self.requested_tx = {}
        self.requested_addrs = {}

    def trigger_callback(self, cbname, data=None):
        if cbname == 'new_transaction':
            self.transactions += 1

    async def subscribe_to_addresses(self, addresses):
        print("subscribing to", len(addresses), "addresses")

        qs = []

        for address in addresses:
            h = address_to_scripthash(address)
            fut, q = self.session.subscribe('blockchain.scripthash.subscribe', h)
            await fut
            qs.append(q)

            yield [address], fut.result()

        async def attachval(fut, aux_data):
            return (await fut), aux_data

        while True:
            jobs = [attachval(x.get(), adr)  for x, adr in zip(qs, addresses)]
            done, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for x in pending: x.cancel()
            for result in done:
                print("LATE SUBSCRIPTION REPLY", data)
                yield [address], result.result()

    async def get_transactions(self, hashes):
        for i in hashes:
            data = await self.session.RPC('blockchain.transaction.get', i)
            yield [i], data

    def get_local_height(self):
        return 10**100

    def add(self, adr):
        self.new_addresses.add(adr)

    def get_status(self, h):
        if not h:
            return None
        status = ''
        for tx_hash, height in h:
            status += tx_hash + ':%d:' % height
        return bh2u(hashlib.sha256(status.encode('ascii')).digest())

    async def on_address_history(self, params, result):
        addr = params[0]
        server_status = self.requested_histories[addr]
        self.print_error("receiving history", addr, len(result))
        hashes = set(map(lambda item: item['tx_hash'], result))
        hist = list(map(lambda item: (item['tx_hash'], item['height']), result))
        # tx_fees
        tx_fees = [(item['tx_hash'], item.get('fee')) for item in result]
        tx_fees = dict(filter(lambda x:x[1] is not None, tx_fees))
        # Check that txids are unique
        if len(hashes) != len(result):
            self.print_error("error: server history has non-unique txids: %s"% addr)
        # Check that the status corresponds to what was announced
        elif self.get_status(hist) != server_status:
            self.print_error("error: status mismatch: %s" % addr)
        else:
            # Store received history
            self.wallet.receive_history_callback(addr, hist, tx_fees)
            # Request transactions we don't have
            # "hist" is a list of [tx_hash, tx_height] lists
            transaction_hashes = []
            for tx_hash, tx_height in hist:
                if tx_hash in self.requested_tx:
                    continue
                if tx_hash in self.wallet.transactions:
                    continue
                transaction_hashes.append(tx_hash)
                self.requested_tx[tx_hash] = tx_height

            if transaction_hashes != []:
                async for tx in self.get_transactions(transaction_hashes):
                    self.on_tx_response(tx)
        # Remove request; this allows up_to_date to be True
        self.requested_histories.pop(addr)

    def on_tx_response(self, response):
        params, result = response
        tx_hash = params[0]
        tx = Transaction(result)
        tx.deserialize()
        assert tx_hash == tx.txid()
        tx_height = self.requested_tx.pop(tx_hash)
        self.wallet.receive_tx_callback(tx_hash, tx, tx_height)
        self.print_error("received tx %s height: %d bytes: %d" %
                         (tx_hash, tx_height, len(tx.raw)))
        # callbacks
        #self.network.trigger_callback('new_transaction', tx)
        #if not self.requested_tx:
        #    self.network.trigger_callback('updated')

    async def main(self):
        connector = StratumClient()
        await connector.connect(ServerInfo({"hostname": conn[0], "ip_addr": conn[0], "ports": {'t'}, 'port': conn[1], 'nickname': 'test', 'version': "1.4", "pruning_limit": False}))
        self.session = connector
        self.wallet.synchronize()

        current_set = set(self.wallet.get_addresses())
        #current_set = self.new_addresses
        self.new_addresses = set()

        generator = MergingAsyncIterator(self.subscribe_to_addresses(current_set))
        async for params, result in generator:
            # on_address_status
            addr = params[0]
            history = self.wallet.history.get(addr, [])
            if self.get_status(history) != result:
                # note that at this point 'result' can be None;
                # if we had a history for addr but now the server is telling us
                # there is no history
                if addr not in self.requested_histories:
                    self.requested_histories[addr] = result

                    # request_address_history
                    sch = address_to_scripthash(addr)
                    req = self.session.RPC("blockchain.scripthash.get_history", sch)
                    await req

                    await self.on_address_history([addr], req.result())
            # remove addr from list only after it is added to requested_histories
            if addr in self.requested_addrs:  # Notifications won't be in
                self.requested_addrs.remove(addr)
            self.wallet.synchronize()
            if self.new_addresses:
                generator.also_yield_from(self.subscribe_to_addresses(self.new_addresses))
                self.new_addresses = set()

logging.basicConfig(level=logging.DEBUG)
loop = asyncio.get_event_loop()
wallet = Wallet(storage)
n = NewNetwork(wallet)
wallet.network = n
wallet.synchronizer = n
loop.run_until_complete(n.main())
print(len(wallet.get_receiving_addresses()))
print(n.transactions)
#print(wallet.history)
#print(wallet.get_local_height())
