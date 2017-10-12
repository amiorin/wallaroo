# Copyright 2017 The Wallaroo Authors.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
#  implied. See the License for the specific language governing
#  permissions and limitations under the License.

import struct
import time

from enum import IntEnum

import wallaroo


FIXTYPE_ORDER = 1
FIXTYPE_MARKET_DATA = 2

SIDETYPE_BUY = 1
SIDETYPE_SELL = 2


def test_python():
    return "hello python"


def str_to_partition(stringable):
    ret = 0
    for x in range(0, len(stringable)):
        ret += ord(stringable[x]) << (x * 8)
    return ret


def load_valid_symbols():
    with open('symbols.txt', 'rb') as f:
        return f.read().splitlines()


def application_setup(args):
    input_addrs = wallaroo.tcp_parse_input_addrs(args)
    order_host, order_port = input_addrs[0]
    nbbo_host, nbbo_port = input_addrs[1]

    out_host, out_port = wallaroo.tcp_parse_output_addrs(args)[0]

    symbol_partitions = [str_to_partition(x.rjust(4)) for x in
                         load_valid_symbols()]

    ab = wallaroo.ApplicationBuilder("market-spread")
    ab.new_pipeline(
            "Orders",
            wallaroo.TCPSourceConfig(order_host, order_port, OrderDecoder())
        ).to_state_partition_u64(
            CheckOrder(), SymbolDataBuilder(), "symbol-data",
            SymbolPartitionFunction(), symbol_partitions
        ).to_sink(
                wallaroo.TCPSinkConfig(
                    out_host, out_port, OrderResultEncoder())
        ).new_pipeline(
            "Market Data",
            wallaroo.TCPSourceConfig(nbbo_host, nbbo_port, MarketDataDecoder())
        ).to_state_partition_u64(
            UpdateMarketData(), SymbolDataBuilder(), "symbol-data",
            SymbolPartitionFunction(), symbol_partitions
        ).done()
    return ab.build()


class SerializedTypes(IntEnum):
    """
    Define the types of data that can be serialised
    """
    UPDATEMARKETDATA = 1
    SYMBOLPARTITIONFUNCTION = 2
    CHECKORDER = 3
    SYMBOLDATABUILDER = 4
    ORDERRESULTENCODER = 5
    MARKETDATAMESSAGE = 6
    MARKETDATADECODER = 7
    ORDERMESSAGE = 8
    ORDERDECODER = 9
    SYMBOLDATA = 10


def serialize(o):
    """
    Pack objects according to the following schema:
    0 - 4b object class (SerializedTypes)
    1 - ?b object data (if required)
    """
    if type(o) is UpdateMarketData:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.UPDATEMARKETDATA)
    elif type(o) is SymbolPartitionFunction:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.SYMBOLPARTITIONFUNCTION)
    elif type(o) is CheckOrder:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.CHECKORDER)
    elif type(o) is SymbolDataBuilder:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.SYMBOLDATABUILDER)
    elif type(o) is OrderResultEncoder:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.ORDERRESULTENCODER)
    elif type(o) is MarketDataMessage:
        s = struct.Struct('>I4s21sdd')
        return s.pack(SerializedTypes.MARKETDATAMESSAGE,
                      o.symbol, o.transact_time, o.bid, o.offer)
    elif type(o) is MarketDataDecoder:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.MARKETDATADECODER)
    elif type(o) is Order:
        s = struct.Struct('>IBI6s4sdd21s')
        return s.pack(SerializedTypes.ORDERMESSAGE, o.side, o.account,
                      o.order_id, o.symbol, o.qty, o.price, o.transact_time)
    elif type(o) is OrderDecoder:
        s = struct.Struct('>I')
        return s.pack(SerializedTypes.ORDERDECODER)
    elif type(o) is SymbolData:
        s = struct.Struct('>Idd?')
        return s.pack(SerializedTypes.SYMBOLDATA,
            o.last_bid, o.last_offer, o.should_reject_trades)
    else:
        print("Don't know how to serialize {}".format(type(o).__name__))
    return None


def deserialize(bs):
    """
    Unpack objects according to the following schema:
    0 - 4b object class (SerializedTypes)
    1 - ?b object data (if required)
    """
    (obj_type,), bs = struct.unpack('>I', bs[:4]), bs[4:]
    if obj_type == SerializedTypes.UPDATEMARKETDATA:
        return UpdateMarketData()
    elif obj_type == SerializedTypes.SYMBOLPARTITIONFUNCTION:
        return SymbolPartitionFunction()
    elif obj_type == SerializedTypes.CHECKORDER:
        return CheckOrder()
    elif obj_type == SerializedTypes.SYMBOLDATABUILDER:
        return SymbolDataBuilder()
    elif obj_type == SerializedTypes.ORDERRESULTENCODER:
        return OrderResultEncoder()
    elif obj_type == SerializedTypes.MARKETDATAMESSAGE:
        (symbol, time, bid, offer) = struct.unpack('>4s21sdd', bs)
        return MarketDataMessage(symbol, time, bid, offer)
    elif obj_type == SerializedTypes.MARKETDATADECODER:
        return MarketDataDecoder()
    elif obj_type == SerializedTypes.ORDERMESSAGE:
        (side, acct, oid, symbol, qty, price, t_time) = struct.unpack(
                '>BI6s4sdd21s', bs)
        return Order(side, acct, oid, symbol, qty, price, t_time)
    elif obj_type == SerializedTypes.ORDERDECODER:
        return OrderDecoder()
    elif obj_type == SerializedTypes.SYMBOLDATA:
        (last_bid, last_offer, should_reject_trades) = struct.unpack('>dd?', bs)
        return SymbolData(last_bid, last_offer, should_reject_trades)
    else:
        print("Don't know how to deserialize: {}".format(obj_type))
    return None


class MarketSpreadError(Exception):
    pass


class SymbolData(object):
    def __init__(self, last_bid, last_offer, should_reject_trades):
        self.last_bid = last_bid
        self.last_offer = last_offer
        self.should_reject_trades = should_reject_trades


class SymbolDataBuilder(object):
    def build(self):
        return SymbolData(0.0, 0.0, True)


class SymbolPartitionFunction(object):
    def partition(self, data):
        return str_to_partition(data.symbol)


class CheckOrder(object):
    def name(self):
        return "Check Order"

    def compute(self, data, state):
        if state.should_reject_trades:
            ts = int(time.time() * 100000)
            return (OrderResult(data, state.last_bid,
                                state.last_offer, ts),
                    False)
        return (None, False)


class Order(object):
    def __init__(self, side, account, order_id, symbol, qty, price,
                 transact_time):
        self.side = side
        self.account = account
        self.order_id = order_id
        self.symbol = symbol
        self.qty = qty
        self.price = price
        self.transact_time = transact_time


class OrderDecoder(object):
    def header_length(self):
        return 4

    def payload_length(self, bs):
        return struct.unpack(">I", bs)[0]

    def decode(self, bs):
        """
        0 -  1b - FixType (U8)
        1 -  1b - side (U8)
        2 -  4b - account (U32)
        6 -  6b - order id (String)
        12 -  4b - symbol (String)
        16 -  8b - order qty (F64)
        24 -  8b - price (F64)
        32 - 21b - transact_time (String)
        """
        order_type = struct.unpack(">B", bs[0:1])[0]
        if order_type != FIXTYPE_ORDER:
            raise MarketSpreadError("Wrong Fix message type {}. Did you "
                                    "connect the senders the wrong way "
                                    "around?".format(order_type))
        side = struct.unpack(">B", bs[1:2])[0]
        account = struct.unpack(">I", bs[2:6])[0]
        order_id = struct.unpack("6s", bs[6:12])[0]
        symbol = struct.unpack("4s", bs[12:16])[0]
        qty = struct.unpack(">d", bs[16:24])[0]
        price = struct.unpack(">d", bs[24:32])[0]
        transact_time = struct.unpack("21s", bs[32:53])[0]

        return Order(side, account, order_id, symbol, qty, price,
                     transact_time)


class OrderResult(object):
    def __init__(self, order, last_bid, last_offer, timestamp):
        self.order = order
        self.bid = last_bid
        self.offer = last_offer
        self.timestamp = timestamp


class OrderResultEncoder(object):
    def encode(self, data):
        p = struct.pack(">HI6s4sddddQ",
                        data.order.side,
                        data.order.account,
                        data.order.order_id,
                        data.order.symbol,
                        data.order.qty,
                        data.order.price,
                        data.bid,
                        data.offer,
                        data.timestamp)
        out = struct.pack('>I{}s'.format(len(p)), len(p), p)
        return out


class MarketDataMessage(object):
    def __init__(self, symbol, transact_time, bid, offer):
        self.symbol = symbol
        self.transact_time = transact_time
        self.bid = bid
        self.offer = offer
        self.mid = (bid + offer) / 2.0


class MarketDataDecoder(object):
    def header_length(self):
        return 4

    def payload_length(self, bs):
        return struct.unpack(">I", bs)[0]

    def decode(self, bs):
        """
        0 -  1b - FixType (U8)
        1 -  4b - symbol (String)
        5 -  21b - transact_time (String)
        26 - 8b - bid_px (F64)
        34 - 8b - offer_px (F64)
        """
        order_type = struct.unpack(">B", bs[0:1])[0]
        if order_type != FIXTYPE_MARKET_DATA:
            raise MarketSpreadError("Wrong Fix message type. Did you connect "
                                    "the senders the wrong way around?")
        symbol = struct.unpack(">4s", bs[1:5])[0]
        transact_time = struct.unpack(">21s", bs[5:26])[0]
        bid = struct.unpack(">d", bs[26:34])[0]
        offer = struct.unpack(">d", bs[34:42])[0]
        return MarketDataMessage(symbol, transact_time, bid, offer)


class UpdateMarketData(object):
    def name(self):
        return "Update Market Data"

    def compute(self, data, state):
        offer_bid_difference = data.offer - data.bid

        should_reject_trades = ((offer_bid_difference >= 0.05) or
                                ((offer_bid_difference / data.mid) >= 0.05))

        state.last_bid = data.bid
        state.last_offer = data.offer
        state.should_reject_trades = should_reject_trades

        return (None, True)
