# Copyright (C) 2018 The Electrum developers
# Copyright (C) 2015-2018 The Lightning Network Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import unittest
import os
import binascii
from pprint import pformat

from electrum import bitcoin
from electrum import lnbase
from electrum import lnchan
from electrum import lnutil
from electrum import bip32 as bip32_utils
from electrum.lnutil import SENT, LOCAL, REMOTE, RECEIVED
from electrum.ecc import sig_string_from_der_sig
from electrum.util import set_verbosity

one_bitcoin_in_msat = bitcoin.COIN * 1000

def create_channel_state(funding_txid, funding_index, funding_sat, local_feerate, is_initiator, local_amount, remote_amount, privkeys, other_pubkeys, seed, cur, nex, other_node_id, l_dust, r_dust, l_csv, r_csv):
    assert local_amount > 0
    assert remote_amount > 0
    channel_id, _ = lnbase.channel_id_from_funding_tx(funding_txid, funding_index)
    their_revocation_store = lnbase.RevocationStore()

    return {
            "channel_id":channel_id,
            "short_channel_id":channel_id[:8],
            "funding_outpoint":lnbase.Outpoint(funding_txid, funding_index),
            "remote_config":lnbase.RemoteConfig(
                payment_basepoint=other_pubkeys[0],
                multisig_key=other_pubkeys[1],
                htlc_basepoint=other_pubkeys[2],
                delayed_basepoint=other_pubkeys[3],
                revocation_basepoint=other_pubkeys[4],
                to_self_delay=r_csv,
                dust_limit_sat=r_dust,
                max_htlc_value_in_flight_msat=one_bitcoin_in_msat * 5,
                max_accepted_htlcs=5,
                initial_msat=remote_amount,
                ctn = -1,
                next_htlc_id = 0,
                reserve_sat=0,

                next_per_commitment_point=nex,
                current_per_commitment_point=cur,
                revocation_store=their_revocation_store,
            ),
            "local_config":lnbase.LocalConfig(
                payment_basepoint=privkeys[0],
                multisig_key=privkeys[1],
                htlc_basepoint=privkeys[2],
                delayed_basepoint=privkeys[3],
                revocation_basepoint=privkeys[4],
                to_self_delay=l_csv,
                dust_limit_sat=l_dust,
                max_htlc_value_in_flight_msat=one_bitcoin_in_msat * 5,
                max_accepted_htlcs=5,
                initial_msat=local_amount,
                ctn = 0,
                next_htlc_id = 0,
                reserve_sat=0,

                per_commitment_secret_seed=seed,
                funding_locked_received=True,
                was_announced=False,
                current_commitment_signature=None,
                current_htlc_signatures=None,
                got_sig_for_next=False,
            ),
            "constraints":lnbase.ChannelConstraints(
                capacity=funding_sat,
                is_initiator=is_initiator,
                funding_txn_minimum_depth=3,
                feerate=local_feerate,
            ),
            "node_id":other_node_id,
            "remote_commitment_to_be_revoked": None,
            'onion_keys': {},
    }

def bip32(sequence):
    xprv, xpub = bip32_utils.bip32_root(b"9dk", 'standard')
    xprv, xpub = bip32_utils.bip32_private_derivation(xprv, "m/", sequence)
    xtype, depth, fingerprint, child_number, c, k = bip32_utils.deserialize_xprv(xprv)
    assert len(k) == 32
    assert type(k) is bytes
    return k

def create_test_channels(feerate=6000, local=None, remote=None):
    funding_txid = binascii.hexlify(b"\x01"*32).decode("ascii")
    funding_index = 0
    funding_sat = ((local + remote) // 1000) if local is not None and remote is not None else (bitcoin.COIN * 10)
    local_amount = local if local is not None else (funding_sat * 1000 // 2)
    remote_amount = remote if remote is not None else (funding_sat * 1000 // 2)
    alice_raw = [ bip32("m/" + str(i)) for i in range(5) ]
    bob_raw = [ bip32("m/" + str(i)) for i in range(5,11) ]
    alice_privkeys = [lnutil.Keypair(lnutil.privkey_to_pubkey(x), x) for x in alice_raw]
    bob_privkeys = [lnutil.Keypair(lnutil.privkey_to_pubkey(x), x) for x in bob_raw]
    alice_pubkeys = [lnutil.OnlyPubkeyKeypair(x.pubkey) for x in alice_privkeys]
    bob_pubkeys = [lnutil.OnlyPubkeyKeypair(x.pubkey) for x in bob_privkeys]

    alice_seed = b"\x01" * 32
    bob_seed = b"\x02" * 32

    alice_first = lnutil.secret_to_pubkey(int.from_bytes(lnutil.get_per_commitment_secret_from_seed(alice_seed, lnutil.RevocationStore.START_INDEX), "big"))
    bob_first = lnutil.secret_to_pubkey(int.from_bytes(lnutil.get_per_commitment_secret_from_seed(bob_seed, lnutil.RevocationStore.START_INDEX), "big"))

    alice, bob = \
        lnchan.Channel(
            create_channel_state(funding_txid, funding_index, funding_sat, feerate, True, local_amount, remote_amount, alice_privkeys, bob_pubkeys, alice_seed, None, bob_first, b"\x02"*33, l_dust=200, r_dust=1300, l_csv=5, r_csv=4), name="alice"), \
        lnchan.Channel(
            create_channel_state(funding_txid, funding_index, funding_sat, feerate, False, remote_amount, local_amount, bob_privkeys, alice_pubkeys, bob_seed, None, alice_first, b"\x01"*33, l_dust=1300, r_dust=200, l_csv=4, r_csv=5), name="bob")

    alice.set_state('OPEN')
    bob.set_state('OPEN')

    a_out = alice.current_commitment(LOCAL).outputs()
    b_out = bob.pending_commitment(REMOTE).outputs()
    assert a_out == b_out, "\n" + pformat((a_out, b_out))

    sig_from_bob, a_htlc_sigs = bob.sign_next_commitment()
    sig_from_alice, b_htlc_sigs = alice.sign_next_commitment()

    assert len(a_htlc_sigs) == 0
    assert len(b_htlc_sigs) == 0

    alice.config[LOCAL] = alice.config[LOCAL]._replace(current_commitment_signature=sig_from_bob)
    bob.config[LOCAL] = bob.config[LOCAL]._replace(current_commitment_signature=sig_from_alice)

    alice.set_local_commitment(alice.current_commitment(LOCAL))
    bob.set_local_commitment(bob.current_commitment(LOCAL))

    alice_second = lnutil.secret_to_pubkey(int.from_bytes(lnutil.get_per_commitment_secret_from_seed(alice_seed, lnutil.RevocationStore.START_INDEX - 1), "big"))
    bob_second = lnutil.secret_to_pubkey(int.from_bytes(lnutil.get_per_commitment_secret_from_seed(bob_seed, lnutil.RevocationStore.START_INDEX - 1), "big"))

    alice.config[REMOTE] = alice.config[REMOTE]._replace(next_per_commitment_point=bob_second, current_per_commitment_point=bob_first)
    bob.config[REMOTE] = bob.config[REMOTE]._replace(next_per_commitment_point=alice_second, current_per_commitment_point=alice_first)

    alice.set_remote_commitment()
    bob.set_remote_commitment()

    alice.remote_commitment_to_be_revoked = alice.remote_commitment
    bob.remote_commitment_to_be_revoked = bob.remote_commitment

    alice.config[REMOTE] = alice.config[REMOTE]._replace(ctn=0)
    bob.config[REMOTE] = bob.config[REMOTE]._replace(ctn=0)

    return alice, bob

class TestFee(unittest.TestCase):
    """
    test
    https://github.com/lightningnetwork/lightning-rfc/blob/e0c436bd7a3ed6a028e1cb472908224658a14eca/03-transactions.md#requirements-2
    """
    def test_fee(self):
        alice_channel, bob_channel = create_test_channels(253, 10000000000, 5000000000)
        self.assertIn(9999817, [x[2] for x in alice_channel.local_commitment.outputs()])

class TestChannel(unittest.TestCase):
    maxDiff = 999

    def assertOutputExistsByValue(self, tx, amt_sat):
        for typ, scr, val in tx.outputs():
            if val == amt_sat:
                break
        else:
            self.assertFalse()

    @staticmethod
    def setUpClass():
        set_verbosity(True)

    def setUp(self):
        # Create a test channel which will be used for the duration of this
        # unittest. The channel will be funded evenly with Alice having 5 BTC,
        # and Bob having 5 BTC.
        self.alice_channel, self.bob_channel = create_test_channels()

        self.paymentPreimage = b"\x01" * 32
        paymentHash = bitcoin.sha256(self.paymentPreimage)
        self.htlc_dict = {
            'payment_hash' : paymentHash,
            'amount_msat' :  one_bitcoin_in_msat,
            'cltv_expiry' :  5,
        }

        # First Alice adds the outgoing HTLC to her local channel's state
        # update log. Then Alice sends this wire message over to Bob who adds
        # this htlc to his remote state update log.
        self.aliceHtlcIndex = self.alice_channel.add_htlc(self.htlc_dict)
        self.assertNotEqual(self.alice_channel.hm.htlcs_by_direction(REMOTE, RECEIVED, 1), set())

        before = self.bob_channel.balance_minus_outgoing_htlcs(REMOTE)
        beforeLocal = self.bob_channel.balance_minus_outgoing_htlcs(LOCAL)

        self.bobHtlcIndex = self.bob_channel.receive_htlc(self.htlc_dict)

        self.assertEqual(1, self.bob_channel.hm.log[LOCAL]['ctn'] + 1)
        self.assertNotEqual(self.bob_channel.hm.htlcs_by_direction(LOCAL, RECEIVED, 1), set())
        after  = self.bob_channel.balance_minus_outgoing_htlcs(REMOTE)
        afterLocal = self.bob_channel.balance_minus_outgoing_htlcs(LOCAL)

        self.assertEqual(before - after, self.htlc_dict['amount_msat'])
        self.assertEqual(beforeLocal, afterLocal)

        self.bob_pending_remote_balance = after

        self.htlc = self.bob_channel.hm.log[REMOTE]['adds'][0]

    def test_concurrent_reversed_payment(self):
        self.htlc_dict['payment_hash'] = bitcoin.sha256(32 * b'\x02')
        self.htlc_dict['amount_msat'] += 1000
        bob_idx = self.bob_channel.add_htlc(self.htlc_dict)
        alice_idx = self.alice_channel.receive_htlc(self.htlc_dict)
        self.alice_channel.receive_new_commitment(*self.bob_channel.sign_next_commitment())
        self.assertEqual(len(self.alice_channel.pending_commitment(REMOTE).outputs()), 4)

    def test_SimpleAddSettleWorkflow(self):
        alice_channel, bob_channel = self.alice_channel, self.bob_channel
        htlc = self.htlc

        alice_out = alice_channel.current_commitment(LOCAL).outputs()
        short_idx, = [idx for idx, x in enumerate(alice_out) if len(x.address) == 42]
        long_idx,  = [idx for idx, x in enumerate(alice_out) if len(x.address) == 62]
        self.assertLess(alice_out[long_idx].value, 5 * 10**8, alice_out)
        self.assertEqual(alice_out[short_idx].value, 5 * 10**8, alice_out)

        alice_out = alice_channel.current_commitment(REMOTE).outputs()
        short_idx, = [idx for idx, x in enumerate(alice_out) if len(x.address) == 42]
        long_idx,  = [idx for idx, x in enumerate(alice_out) if len(x.address) == 62]
        self.assertLess(alice_out[short_idx].value, 5 * 10**8)
        self.assertEqual(alice_out[long_idx].value, 5 * 10**8)

        def com():
            return alice_channel.local_commitment

        self.assertTrue(alice_channel.signature_fits(com()))

        self.assertNotEqual(alice_channel.included_htlcs(REMOTE, RECEIVED, 1), [])
        self.assertEqual({0: [], 1: [htlc]}, alice_channel.included_htlcs_in_their_latest_ctxs(LOCAL))
        self.assertNotEqual(bob_channel.included_htlcs(REMOTE, SENT, 1), [])
        self.assertEqual({0: [], 1: [htlc]}, bob_channel.included_htlcs_in_their_latest_ctxs(REMOTE))
        self.assertEqual({0: [], 1: []}, alice_channel.included_htlcs_in_their_latest_ctxs(REMOTE))
        self.assertEqual({0: [], 1: []}, bob_channel.included_htlcs_in_their_latest_ctxs(LOCAL))

        from electrum.lnutil import extract_ctn_from_tx_and_chan
        tx0 = str(alice_channel.force_close_tx())
        self.assertEqual(alice_channel.config[LOCAL].ctn, 0)
        self.assertEqual(extract_ctn_from_tx_and_chan(alice_channel.force_close_tx(), alice_channel), 0)
        self.assertTrue(alice_channel.signature_fits(alice_channel.current_commitment(LOCAL)))

        # Next alice commits this change by sending a signature message. Since
        # we expect the messages to be ordered, Bob will receive the HTLC we
        # just sent before he receives this signature, so the signature will
        # cover the HTLC.
        aliceSig, aliceHtlcSigs = alice_channel.sign_next_commitment()
        self.assertEqual(len(aliceHtlcSigs), 1, "alice should generate one htlc signature")

        self.assertTrue(alice_channel.signature_fits(com()))
        self.assertEqual(str(alice_channel.current_commitment(LOCAL)), str(com()))

        self.assertEqual(next(iter(alice_channel.hm.pending_htlcs(REMOTE)))[0], RECEIVED)
        self.assertEqual(alice_channel.hm.pending_htlcs(REMOTE), bob_channel.hm.pending_htlcs(LOCAL))
        self.assertEqual(alice_channel.pending_commitment(REMOTE).outputs(), bob_channel.pending_commitment(LOCAL).outputs())

        # Bob receives this signature message, and checks that this covers the
        # state he has in his remote log. This includes the HTLC just sent
        # from Alice.
        self.assertTrue(bob_channel.signature_fits(bob_channel.current_commitment(LOCAL)))
        bob_channel.receive_new_commitment(aliceSig, aliceHtlcSigs)
        self.assertTrue(bob_channel.signature_fits(bob_channel.pending_commitment(LOCAL)))

        self.assertEqual(bob_channel.config[REMOTE].ctn, 0)
        self.assertEqual(bob_channel.included_htlcs(REMOTE, SENT, 1), [htlc])

        self.assertEqual({0: [], 1: [htlc]}, alice_channel.included_htlcs_in_their_latest_ctxs(LOCAL))
        self.assertEqual({0: [], 1: [htlc]}, bob_channel.included_htlcs_in_their_latest_ctxs(REMOTE))
        self.assertEqual({0: [], 1: []}, alice_channel.included_htlcs_in_their_latest_ctxs(REMOTE))
        self.assertEqual({0: [], 1: []}, bob_channel.included_htlcs_in_their_latest_ctxs(LOCAL))

        # Bob revokes his prior commitment given to him by Alice, since he now
        # has a valid signature for a newer commitment.
        bobRevocation, _ = bob_channel.revoke_current_commitment()
        bob_channel.serialize()
        self.assertTrue(bob_channel.signature_fits(bob_channel.current_commitment(LOCAL)))

        # Bob finally sends a signature for Alice's commitment transaction.
        # This signature will cover the HTLC, since Bob will first send the
        # revocation just created. The revocation also acks every received
        # HTLC up to the point where Alice sent her signature.
        bobSig, bobHtlcSigs = bob_channel.sign_next_commitment()
        self.assertTrue(bob_channel.signature_fits(bob_channel.current_commitment(LOCAL)))

        self.assertEqual(len(bobHtlcSigs), 1)

        self.assertTrue(alice_channel.signature_fits(com()))
        self.assertEqual(str(alice_channel.current_commitment(LOCAL)), str(com()))

        self.assertEqual(len(alice_channel.pending_commitment(LOCAL).outputs()), 3)

        # Alice then processes this revocation, sending her own revocation for
        # her prior commitment transaction. Alice shouldn't have any HTLCs to
        # forward since she's sending an outgoing HTLC.
        alice_channel.receive_revocation(bobRevocation)
        alice_channel.serialize()
        self.assertEqual(alice_channel.remote_commitment.outputs(), alice_channel.current_commitment(REMOTE).outputs())

        self.assertTrue(alice_channel.signature_fits(com()))
        self.assertTrue(alice_channel.signature_fits(alice_channel.current_commitment(LOCAL)))
        alice_channel.serialize()
        self.assertEqual(str(alice_channel.current_commitment(LOCAL)), str(com()))

        self.assertEqual(len(alice_channel.current_commitment(LOCAL).outputs()), 2)
        self.assertEqual(len(alice_channel.current_commitment(REMOTE).outputs()), 3)
        self.assertEqual(len(com().outputs()), 2)
        self.assertEqual(len(alice_channel.force_close_tx().outputs()), 2)

        self.assertEqual(alice_channel.hm.log.keys(), set([LOCAL, REMOTE]))
        self.assertEqual(len(alice_channel.hm.log[LOCAL]['adds']), 1)
        alice_channel.serialize()

        self.assertEqual(alice_channel.pending_commitment(LOCAL).outputs(),
                         bob_channel.pending_commitment(REMOTE).outputs())

        # Alice then processes bob's signature, and since she just received
        # the revocation, she expect this signature to cover everything up to
        # the point where she sent her signature, including the HTLC.
        alice_channel.receive_new_commitment(bobSig, bobHtlcSigs)
        self.assertEqual(alice_channel.remote_commitment.outputs(), alice_channel.current_commitment(REMOTE).outputs())

        self.assertEqual(len(alice_channel.current_commitment(REMOTE).outputs()), 3)
        self.assertEqual(len(com().outputs()), 3)
        self.assertEqual(len(alice_channel.force_close_tx().outputs()), 3)

        self.assertEqual(len(alice_channel.hm.log[LOCAL]['adds']), 1)
        alice_channel.serialize()

        tx1 = str(alice_channel.force_close_tx())
        self.assertNotEqual(tx0, tx1)

        # Alice then generates a revocation for bob.
        self.assertEqual(alice_channel.remote_commitment.outputs(), alice_channel.current_commitment(REMOTE).outputs())
        aliceRevocation, _ = alice_channel.revoke_current_commitment()
        alice_channel.serialize()
        #self.assertEqual(alice_channel.remote_commitment.outputs(), alice_channel.current_commitment(REMOTE).outputs())

        tx2 = str(alice_channel.force_close_tx())
        # since alice already has the signature for the next one, it doesn't change her force close tx (it was already the newer one)
        self.assertEqual(tx1, tx2)

        # Finally Bob processes Alice's revocation, at this point the new HTLC
        # is fully locked in within both commitment transactions. Bob should
        # also be able to forward an HTLC now that the HTLC has been locked
        # into both commitment transactions.
        self.assertTrue(bob_channel.signature_fits(bob_channel.current_commitment(LOCAL)))
        bob_channel.receive_revocation(aliceRevocation)
        bob_channel.serialize()

        # At this point, both sides should have the proper number of satoshis
        # sent, and commitment height updated within their local channel
        # state.
        aliceSent = 0
        bobSent = 0

        self.assertEqual(alice_channel.total_msat(SENT), aliceSent, "alice has incorrect milli-satoshis sent")
        self.assertEqual(alice_channel.total_msat(RECEIVED), bobSent, "alice has incorrect milli-satoshis received")
        self.assertEqual(bob_channel.total_msat(SENT), bobSent, "bob has incorrect milli-satoshis sent")
        self.assertEqual(bob_channel.total_msat(RECEIVED), aliceSent, "bob has incorrect milli-satoshis received")
        self.assertEqual(bob_channel.config[LOCAL].ctn, 1, "bob has incorrect commitment height")
        self.assertEqual(alice_channel.config[LOCAL].ctn, 1, "alice has incorrect commitment height")

        # Both commitment transactions should have three outputs, and one of
        # them should be exactly the amount of the HTLC.
        alice_ctx = alice_channel.pending_commitment(LOCAL)
        bob_ctx = bob_channel.pending_commitment(LOCAL)
        self.assertEqual(len(alice_ctx.outputs()), 3, "alice should have three commitment outputs, instead have %s"% len(alice_ctx.outputs()))
        self.assertEqual(len(bob_ctx.outputs()), 3, "bob should have three commitment outputs, instead have %s"% len(bob_ctx.outputs()))
        self.assertOutputExistsByValue(alice_ctx, htlc.amount_msat // 1000)
        self.assertOutputExistsByValue(bob_ctx, htlc.amount_msat // 1000)

        # Now we'll repeat a similar exchange, this time with Bob settling the
        # HTLC once he learns of the preimage.
        preimage = self.paymentPreimage
        bob_channel.settle_htlc(preimage, self.bobHtlcIndex)

        #self.assertEqual(alice_channel.remote_commitment.outputs(), alice_channel.current_commitment(REMOTE).outputs())
        alice_channel.receive_htlc_settle(preimage, self.aliceHtlcIndex)

        tx3 = str(alice_channel.force_close_tx())
        # just settling a htlc does not change her force close tx
        self.assertEqual(tx2, tx3)

        bobSig2, bobHtlcSigs2 = bob_channel.sign_next_commitment()
        self.assertEqual(len(bobHtlcSigs2), 0)

        self.assertEqual(alice_channel.hm.htlcs_by_direction(REMOTE, RECEIVED), [htlc])
        self.assertEqual(alice_channel.included_htlcs(REMOTE, RECEIVED, alice_channel.config[REMOTE].ctn), [htlc])
        self.assertEqual({1: [htlc], 2: []}, alice_channel.included_htlcs_in_their_latest_ctxs(LOCAL))
        self.assertEqual({1: [htlc], 2: []}, bob_channel.included_htlcs_in_their_latest_ctxs(REMOTE))
        self.assertEqual({1: [], 2: []}, alice_channel.included_htlcs_in_their_latest_ctxs(REMOTE))
        self.assertEqual({1: [], 2: []}, bob_channel.included_htlcs_in_their_latest_ctxs(LOCAL))

        alice_ctx_bob_version = bob_channel.pending_commitment(REMOTE).outputs()
        alice_ctx_alice_version = alice_channel.pending_commitment(LOCAL).outputs()
        self.assertEqual(alice_ctx_alice_version, alice_ctx_bob_version)

        alice_channel.receive_new_commitment(bobSig2, bobHtlcSigs2)

        tx4 = str(alice_channel.force_close_tx())
        self.assertNotEqual(tx3, tx4)

        self.assertEqual(alice_channel.balance(LOCAL), 500000000000)
        self.assertEqual(1, alice_channel.config[LOCAL].ctn)
        self.assertEqual(len(alice_channel.included_htlcs(LOCAL, RECEIVED, ctn=2)), 0)
        aliceRevocation2, _ = alice_channel.revoke_current_commitment()
        alice_channel.serialize()
        aliceSig2, aliceHtlcSigs2 = alice_channel.sign_next_commitment()
        self.assertEqual(aliceHtlcSigs2, [], "alice should generate no htlc signatures")
        self.assertEqual(len(bob_channel.current_commitment(LOCAL).outputs()), 3)
        self.assertEqual(len(bob_channel.pending_commitment(LOCAL).outputs()), 2)
        received, sent = bob_channel.receive_revocation(aliceRevocation2)
        bob_channel.serialize()
        self.assertEqual(received, one_bitcoin_in_msat)

        bob_channel.receive_new_commitment(aliceSig2, aliceHtlcSigs2)

        bobRevocation2, _ = bob_channel.revoke_current_commitment()
        bob_channel.serialize()
        alice_channel.receive_revocation(bobRevocation2)
        alice_channel.serialize()

        # At this point, Bob should have 6 BTC settled, with Alice still having
        # 4 BTC. Alice's channel should show 1 BTC sent and Bob's channel
        # should show 1 BTC received. They should also be at commitment height
        # two, with the revocation window extended by 1 (5).
        mSatTransferred = one_bitcoin_in_msat
        self.assertEqual(alice_channel.total_msat(SENT), mSatTransferred, "alice satoshis sent incorrect")
        self.assertEqual(alice_channel.total_msat(RECEIVED), 0, "alice satoshis received incorrect")
        self.assertEqual(bob_channel.total_msat(RECEIVED), mSatTransferred, "bob satoshis received incorrect")
        self.assertEqual(bob_channel.total_msat(SENT), 0, "bob satoshis sent incorrect")
        self.assertEqual(bob_channel.current_height[LOCAL], 2, "bob has incorrect commitment height")
        self.assertEqual(alice_channel.current_height[LOCAL], 2, "alice has incorrect commitment height")

        self.assertEqual(self.bob_pending_remote_balance, self.alice_channel.balance(LOCAL))

        alice_channel.update_fee(100000, True)
        alice_outputs = alice_channel.pending_commitment(REMOTE).outputs()
        old_outputs = bob_channel.pending_commitment(LOCAL).outputs()
        bob_channel.update_fee(100000, False)
        new_outputs = bob_channel.pending_commitment(LOCAL).outputs()
        self.assertNotEqual(old_outputs, new_outputs)
        self.assertEqual(alice_outputs, new_outputs)

        tx5 = str(alice_channel.force_close_tx())
        # sending a fee update does not change her force close tx
        self.assertEqual(tx4, tx5)

        force_state_transition(alice_channel, bob_channel)

        tx6 = str(alice_channel.force_close_tx())
        self.assertNotEqual(tx5, tx6)

        self.htlc_dict['amount_msat'] *= 5
        bob_index = bob_channel.add_htlc(self.htlc_dict)
        alice_index = alice_channel.receive_htlc(self.htlc_dict)

        bob_channel.pending_commitment(REMOTE)
        alice_channel.pending_commitment(LOCAL)

        alice_channel.pending_commitment(REMOTE)
        bob_channel.pending_commitment(LOCAL)

        force_state_transition(bob_channel, alice_channel)
        alice_channel.settle_htlc(self.paymentPreimage, alice_index)
        bob_channel.receive_htlc_settle(self.paymentPreimage, bob_index)
        force_state_transition(bob_channel, alice_channel)
        self.assertEqual(alice_channel.total_msat(SENT), one_bitcoin_in_msat, "alice satoshis sent incorrect")
        self.assertEqual(alice_channel.total_msat(RECEIVED), 5 * one_bitcoin_in_msat, "alice satoshis received incorrect")
        self.assertEqual(bob_channel.total_msat(RECEIVED), one_bitcoin_in_msat, "bob satoshis received incorrect")
        self.assertEqual(bob_channel.total_msat(SENT), 5 * one_bitcoin_in_msat, "bob satoshis sent incorrect")

        alice_channel.serialize()


    def alice_to_bob_fee_update(self, fee=111):
        aoldctx = self.alice_channel.pending_commitment(REMOTE).outputs()
        self.alice_channel.update_fee(fee, True)
        anewctx = self.alice_channel.pending_commitment(REMOTE).outputs()
        self.assertNotEqual(aoldctx, anewctx)
        boldctx = self.bob_channel.pending_commitment(LOCAL).outputs()
        self.bob_channel.update_fee(fee, False)
        bnewctx = self.bob_channel.pending_commitment(LOCAL).outputs()
        self.assertNotEqual(boldctx, bnewctx)
        self.assertEqual(anewctx, bnewctx)
        return fee

    def test_UpdateFeeSenderCommits(self):
        old_feerate = self.alice_channel.pending_feerate(LOCAL)
        fee = self.alice_to_bob_fee_update()

        alice_channel, bob_channel = self.alice_channel, self.bob_channel

        self.assertEqual(self.alice_channel.pending_feerate(LOCAL), old_feerate)
        alice_sig, alice_htlc_sigs = alice_channel.sign_next_commitment()
        self.assertEqual(self.alice_channel.pending_feerate(LOCAL), old_feerate)

        bob_channel.receive_new_commitment(alice_sig, alice_htlc_sigs)

        self.assertNotEqual(fee, bob_channel.constraints.feerate)
        rev, _ = bob_channel.revoke_current_commitment()
        self.assertEqual(fee, bob_channel.constraints.feerate)

        bob_sig, bob_htlc_sigs = bob_channel.sign_next_commitment()
        alice_channel.receive_revocation(rev)
        alice_channel.receive_new_commitment(bob_sig, bob_htlc_sigs)

        self.assertNotEqual(fee, alice_channel.constraints.feerate)
        rev, _ = alice_channel.revoke_current_commitment()
        self.assertEqual(fee, alice_channel.constraints.feerate)

        bob_channel.receive_revocation(rev)
        self.assertEqual(fee, bob_channel.constraints.feerate)


    def test_UpdateFeeReceiverCommits(self):
        fee = self.alice_to_bob_fee_update()

        alice_channel, bob_channel = self.alice_channel, self.bob_channel

        bob_sig, bob_htlc_sigs = bob_channel.sign_next_commitment()
        alice_channel.receive_new_commitment(bob_sig, bob_htlc_sigs)

        alice_revocation, _ = alice_channel.revoke_current_commitment()
        bob_channel.receive_revocation(alice_revocation)
        alice_sig, alice_htlc_sigs = alice_channel.sign_next_commitment()
        bob_channel.receive_new_commitment(alice_sig, alice_htlc_sigs)

        self.assertNotEqual(fee, bob_channel.constraints.feerate)
        bob_revocation, _ = bob_channel.revoke_current_commitment()
        self.assertEqual(fee, bob_channel.constraints.feerate)

        bob_sig, bob_htlc_sigs = bob_channel.sign_next_commitment()
        alice_channel.receive_revocation(bob_revocation)
        alice_channel.receive_new_commitment(bob_sig, bob_htlc_sigs)

        self.assertNotEqual(fee, alice_channel.constraints.feerate)
        alice_revocation, _ = alice_channel.revoke_current_commitment()
        self.assertEqual(fee, alice_channel.constraints.feerate)

        bob_channel.receive_revocation(alice_revocation)
        self.assertEqual(fee, bob_channel.constraints.feerate)

    def test_AddHTLCNegativeBalance(self):
        # the test in lnd doesn't set the fee to zero.
        # probably lnd subtracts commitment fee after deciding weather
        # an htlc can be added. so we set the fee to zero so that
        # the test can work.
        self.alice_to_bob_fee_update(0)
        force_state_transition(self.alice_channel, self.bob_channel)

        self.htlc_dict['payment_hash'] = bitcoin.sha256(32 * b'\x02')
        self.alice_channel.add_htlc(self.htlc_dict)
        self.htlc_dict['payment_hash'] = bitcoin.sha256(32 * b'\x03')
        self.alice_channel.add_htlc(self.htlc_dict)
        # now there are three htlcs (one was in setUp)

        # Alice now has an available balance of 2 BTC. We'll add a new HTLC of
        # value 2 BTC, which should make Alice's balance negative (since she
        # has to pay a commitment fee).
        new = dict(self.htlc_dict)
        new['amount_msat'] *= 2.5
        new['payment_hash'] = bitcoin.sha256(32 * b'\x04')
        with self.assertRaises(lnutil.PaymentFailure) as cm:
            self.alice_channel.add_htlc(new)
        self.assertIn('Not enough local balance', cm.exception.args[0])

    def test_sign_commitment_is_pure(self):
        force_state_transition(self.alice_channel, self.bob_channel)
        self.htlc_dict['payment_hash'] = bitcoin.sha256(b'\x02' * 32)
        aliceHtlcIndex = self.alice_channel.add_htlc(self.htlc_dict)
        before_signing = self.alice_channel.to_save()
        self.alice_channel.sign_next_commitment()
        after_signing = self.alice_channel.to_save()
        try:
            self.assertEqual(before_signing, after_signing)
        except:
            try:
                from deepdiff import DeepDiff
            except ImportError:
                raise
            raise Exception(pformat(DeepDiff(before_signing, after_signing)))

class TestAvailableToSpend(unittest.TestCase):
    def test_DesyncHTLCs(self):
        alice_channel, bob_channel = create_test_channels()

        paymentPreimage = b"\x01" * 32
        paymentHash = bitcoin.sha256(paymentPreimage)
        htlc_dict = {
            'payment_hash' : paymentHash,
            'amount_msat' :  int(4.1 * one_bitcoin_in_msat),
            'cltv_expiry' :  5,
        }

        alice_idx = alice_channel.add_htlc(htlc_dict)
        bob_idx = bob_channel.receive_htlc(htlc_dict)
        force_state_transition(alice_channel, bob_channel)
        bob_channel.fail_htlc(bob_idx)
        alice_channel.receive_fail_htlc(alice_idx)
        # Alice now has gotten all her original balance (5 BTC) back, however,
        # adding a new HTLC at this point SHOULD fail, since if she adds the
        # HTLC and signs the next state, Bob cannot assume she received the
        # FailHTLC, and must assume she doesn't have the necessary balance
        # available.
        # We try adding an HTLC of value 1 BTC, which should fail because the
        # balance is unavailable.
        htlc_dict = {
            'payment_hash' : paymentHash,
            'amount_msat' :  one_bitcoin_in_msat,
            'cltv_expiry' :  5,
        }
        with self.assertRaises(lnutil.PaymentFailure):
            alice_channel.add_htlc(htlc_dict)
        # Now do a state transition, which will ACK the FailHTLC, making Alice
        # able to add the new HTLC.
        force_state_transition(alice_channel, bob_channel)
        alice_channel.add_htlc(htlc_dict)

class TestChanReserve(unittest.TestCase):
    def setUp(self):
        alice_channel, bob_channel = create_test_channels()
        alice_min_reserve = int(.5 * one_bitcoin_in_msat // 1000)
        # We set Bob's channel reserve to a value that is larger than
        # his current balance in the channel. This will ensure that
        # after a channel is first opened, Bob can still receive HTLCs
        # even though his balance is less than his channel reserve.
        bob_min_reserve = 6 * one_bitcoin_in_msat // 1000
        # bob min reserve was decided by alice, but applies to bob

        alice_channel.config[LOCAL] =\
            alice_channel.config[LOCAL]._replace(reserve_sat=bob_min_reserve)
        alice_channel.config[REMOTE] =\
            alice_channel.config[REMOTE]._replace(reserve_sat=alice_min_reserve)

        bob_channel.config[LOCAL] =\
            bob_channel.config[LOCAL]._replace(reserve_sat=alice_min_reserve)
        bob_channel.config[REMOTE] =\
            bob_channel.config[REMOTE]._replace(reserve_sat=bob_min_reserve)

        self.alice_channel = alice_channel
        self.bob_channel = bob_channel

    def test_part1(self):
        # Add an HTLC that will increase Bob's balance. This should succeed,
        # since Alice stays above her channel reserve, and Bob increases his
        # balance (while still being below his channel reserve).
        #
        # Resulting balances:
        #	Alice:	4.5
        #	Bob:	5.0
        paymentPreimage = b"\x01" * 32
        paymentHash = bitcoin.sha256(paymentPreimage)
        htlc_dict = {
            'payment_hash' : paymentHash,
            'amount_msat' :  int(.5 * one_bitcoin_in_msat),
            'cltv_expiry' :  5,
        }
        self.alice_channel.add_htlc(htlc_dict)
        self.bob_channel.receive_htlc(htlc_dict)
        # Force a state transition, making sure this HTLC is considered valid
        # even though the channel reserves are not met.
        force_state_transition(self.alice_channel, self.bob_channel)

        aliceSelfBalance = self.alice_channel.balance(LOCAL)\
                - lnchan.htlcsum(self.alice_channel.hm.htlcs_by_direction(LOCAL, SENT))
        bobBalance = self.bob_channel.balance(REMOTE)\
                - lnchan.htlcsum(self.alice_channel.hm.htlcs_by_direction(REMOTE, SENT))
        self.assertEqual(aliceSelfBalance, one_bitcoin_in_msat*4.5)
        self.assertEqual(bobBalance, one_bitcoin_in_msat*5)
        # Now let Bob try to add an HTLC. This should fail, since it will
        # decrease his balance, which is already below the channel reserve.
        #
        # Resulting balances:
        #	Alice:	4.5
        #	Bob:	5.0
        with self.assertRaises(lnutil.PaymentFailure):
            htlc_dict['payment_hash'] = bitcoin.sha256(32 * b'\x02')
            self.bob_channel.add_htlc(htlc_dict)
        with self.assertRaises(lnutil.RemoteMisbehaving):
            self.alice_channel.receive_htlc(htlc_dict)

    def part2(self):
        paymentPreimage = b"\x01" * 32
        paymentHash = bitcoin.sha256(paymentPreimage)
        # Now we'll add HTLC of 3.5 BTC to Alice's commitment, this should put
        # Alice's balance at 1.5 BTC.
        #
        # Resulting balances:
        #	Alice:	1.5
        #	Bob:	9.5
        htlc_dict = {
            'payment_hash' : paymentHash,
            'amount_msat' :  int(3.5 * one_bitcoin_in_msat),
            'cltv_expiry' :  5,
        }
        self.alice_channel.add_htlc(htlc_dict)
        self.bob_channel.receive_htlc(htlc_dict)
        # Add a second HTLC of 1 BTC. This should fail because it will take
        # Alice's balance all the way down to her channel reserve, but since
        # she is the initiator the additional transaction fee makes her
        # balance dip below.
        htlc_dict['amount_msat'] = one_bitcoin_in_msat
        with self.assertRaises(lnutil.PaymentFailure):
            self.alice_channel.add_htlc(htlc_dict)
        with self.assertRaises(lnutil.RemoteMisbehaving):
            self.bob_channel.receive_htlc(htlc_dict)

    def part3(self):
        # Add a HTLC of 2 BTC to Alice, and the settle it.
        # Resulting balances:
        #	Alice:	3.0
        #	Bob:	7.0
        htlc_dict = {
            'payment_hash' : paymentHash,
            'amount_msat' :  int(2 * one_bitcoin_in_msat),
            'cltv_expiry' :  5,
        }
        alice_idx = self.alice_channel.add_htlc(htlc_dict)
        bob_idx = self.bob_channel.receive_htlc(htlc_dict)
        force_state_transition(self.alice_channel, self.bob_channel)
        self.check_bals(one_bitcoin_in_msat*3\
                - self.alice_channel.pending_local_fee(),
                  one_bitcoin_in_msat*5)
        self.bob_channel.settle_htlc(paymentPreimage, bob_idx)
        self.alice_channel.receive_htlc_settle(paymentPreimage, alice_idx)
        force_state_transition(self.alice_channel, self.bob_channel)
        self.check_bals(one_bitcoin_in_msat*3\
                - self.alice_channel.pending_local_fee(),
                  one_bitcoin_in_msat*7)
        # And now let Bob add an HTLC of 1 BTC. This will take Bob's balance
        # all the way down to his channel reserve, but since he is not paying
        # the fee this is okay.
        htlc_dict['amount_msat'] = one_bitcoin_in_msat
        self.bob_channel.add_htlc(htlc_dict)
        self.alice_channel.receive_htlc(htlc_dict)
        force_state_transition(self.alice_channel, self.bob_channel)
        self.check_bals(one_bitcoin_in_msat*3\
                - self.alice_channel.pending_local_fee(),
                  one_bitcoin_in_msat*6)

    def check_bals(self, amt1, amt2):
        self.assertEqual(self.alice_channel.available_to_spend(LOCAL), amt1)
        self.assertEqual(self.bob_channel.available_to_spend(REMOTE), amt1)
        self.assertEqual(self.alice_channel.available_to_spend(REMOTE), amt2)
        self.assertEqual(self.bob_channel.available_to_spend(LOCAL), amt2)

class TestDust(unittest.TestCase):
    def test_DustLimit(self):
        alice_channel, bob_channel = create_test_channels()

        paymentPreimage = b"\x01" * 32
        paymentHash = bitcoin.sha256(paymentPreimage)
        fee_per_kw = alice_channel.constraints.feerate
        self.assertEqual(fee_per_kw, 6000)
        htlcAmt = 500 + lnutil.HTLC_TIMEOUT_WEIGHT * (fee_per_kw // 1000)
        self.assertEqual(htlcAmt, 4478)
        htlc = {
            'payment_hash' : paymentHash,
            'amount_msat' :  1000 * htlcAmt,
            'cltv_expiry' :  5, # also in create_test_channels
        }

        old_values = [x.value for x in bob_channel.current_commitment(LOCAL).outputs() ]
        aliceHtlcIndex = alice_channel.add_htlc(htlc)
        bobHtlcIndex = bob_channel.receive_htlc(htlc)
        force_state_transition(alice_channel, bob_channel)
        alice_ctx = alice_channel.current_commitment(LOCAL)
        bob_ctx = bob_channel.current_commitment(LOCAL)
        new_values = [x.value for x in bob_ctx.outputs() ]
        self.assertNotEqual(old_values, new_values)
        self.assertEqual(len(alice_ctx.outputs()), 3)
        self.assertEqual(len(bob_ctx.outputs()), 2)
        default_fee = calc_static_fee(0)
        self.assertEqual(bob_channel.pending_local_fee(), default_fee + htlcAmt)
        bob_channel.settle_htlc(paymentPreimage, bobHtlcIndex)
        alice_channel.receive_htlc_settle(paymentPreimage, aliceHtlcIndex)
        force_state_transition(bob_channel, alice_channel)
        self.assertEqual(len(alice_channel.pending_commitment(LOCAL).outputs()), 2)
        self.assertEqual(alice_channel.total_msat(SENT) // 1000, htlcAmt)

def force_state_transition(chanA, chanB):
    chanB.receive_new_commitment(*chanA.sign_next_commitment())
    rev, _ = chanB.revoke_current_commitment()
    bob_sig, bob_htlc_sigs = chanB.sign_next_commitment()
    chanA.receive_revocation(rev)
    chanA.receive_new_commitment(bob_sig, bob_htlc_sigs)
    chanB.receive_revocation(chanA.revoke_current_commitment()[0])

# calcStaticFee calculates appropriate fees for commitment transactions.  This
# function provides a simple way to allow test balance assertions to take fee
# calculations into account.
def calc_static_fee(numHTLCs):
    commitWeight = 724
    htlcWeight   = 172
    feePerKw     = 24//4 * 1000
    return feePerKw * (commitWeight + htlcWeight*numHTLCs) // 1000
