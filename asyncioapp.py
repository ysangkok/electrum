import trio
import traceback
import sys
from electrum.network import Network
from electrum.storage import WalletStorage
from electrum.wallet import Wallet
from electrum.exchange_rate import FxThread

class FakeDaemon:
    def __init__(self, nursery, config):
        self.network = Network(nursery, config)
        self.network.start()
        self.fx = FxThread(config, self.network)
        self.wallets = {}
    def load_wallet(self, path, password):
        # wizard will be launched if we return
        if path in self.wallets:
            wallet = self.wallets[path]
            return wallet
        storage = WalletStorage(path, manual_upgrades=True)
        if not storage.file_exists():
            return
        if storage.is_encrypted():
            if not password:
                return
            storage.decrypt(password)
        if storage.requires_split():
            return
        if storage.get_action():
            return
        wallet = Wallet(storage)
        wallet.start_threads(self.network)
        self.wallets[path] = wallet
        return wallet
    def stop_wallet(self, path):
        pass


def init_gui(config, plugins, nursery):
    gui_name = config.get('gui', 'qt')
    if gui_name in ['lite', 'classic']:
        gui_name = 'qt'
    gui = __import__('electrum_gui.' + gui_name, fromlist=['electrum_gui'])
    guiobj = gui.ElectrumGui(config, FakeDaemon(nursery, config), plugins)
    nursery.start_soon(guiobj.async_run)
