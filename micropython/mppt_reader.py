import aioble
import bluetooth
import sys
import asyncio
import common


class RequestItem:
    def __init__(self,
                 dec_address: str,
                 description: str,
                 multiplier: int,
                 unit: str,
                 skip: bool = False):
        self.dec_address = dec_address
        self.description = description
        self.multiplier = multiplier
        self.unit = unit
        self.skip = skip


class ResponseItem:
    def __init__(self,
                 description: str,
                 value: float,
                 unit: str):
        self.description = description
        self.value = value
        self.unit = unit


class MpptReader:
    def __init__(self,
                 device_address: str,
                 service_uuid: int,
                 write_char_uuid: int,
                 notify_char_uuid: int,
                 logging: bool = False):

        self.device_address = device_address
        self.service_uuid = service_uuid
        self.write_char_uuid = write_char_uuid
        self.notify_char_uuid = notify_char_uuid

        self.logging = logging

    async def read(self, request_items: list[RequestItem]) -> list[ResponseItem]:
        data = []

        try:
            data = await self.__process(request_items)

        except Exception as e:
            self.__log("error while reading mppt data...")
            sys.print_exception(e)

        return data

    async def __get_characteristic(self, service: aioble.Service, uuid: int) -> aioble.Characteristic | None:
        char = await service.characteristic(bluetooth.UUID(uuid))
        return char

    async def __setup_connection(self, connection: aioble.central.DeviceConnection) -> tuple[
        aioble.Characteristic, aioble.Characteristic]:

        try:
            service: aioble.Service = await connection.service(bluetooth.UUID(self.service_uuid))

            write_char = await self.__get_characteristic(service, self.write_char_uuid)
            notify_char = await self.__get_characteristic(service, self.notify_char_uuid)

            self.__log("subscribing for notifications...")
            await notify_char.subscribe(notify=True)

        except Exception as e:
            raise Exception(f"error while setting up connection: {str(e)}")

        return write_char, notify_char

    async def __process(self, request_items: list[RequestItem]) -> list[ResponseItem]:
        self.__log("connecting to target...")
        connection = await self.__connect_to_device(connection_timeout=5000)

        if connection:
            self.__log(f"connected to {connection.device}")

            async with connection:
                write_char, notify_char = await self.__setup_connection(connection)

                first_item_hex_address = "%x" % int(request_items[0].dec_address)
                write_buff = common.get_buff(first_item_hex_address, count=len(request_items))

                self.__log(f"writing buff {write_buff}")
                await write_char.write(write_buff)

                self.__log("waiting for response")
                response_items = await self.__process_response(notify_char, request_items)

        self.__log("done")

        return response_items

    async def __process_response(self,
                                 notify_char: aioble.Characteristic,
                                 request_items: list[RequestItem]) -> list[ResponseItem]:
        data_str = ""

        while True:
            data = await notify_char.notified(timeout_ms=5000)
            data = data.hex()

            if data:
                data_str += data
                length_match = (10 + (len(request_items) * 4)) == len(data_str)

                if length_match:
                    crc = common.modbus_crc(data_str[:-4]) if len(data_str) > 4 else None

                    if crc and data_str.endswith(crc):
                        self.__log(f"[Notification] done. data: {data_str} | crc: {crc}")
                        break

                self.__log(f"[Notification] {data}")

        return self.__process_data(data_str, request_items)

    def __process_data(self, data: str, request_items: list[RequestItem]) -> list[ResponseItem]:
        response_data: list[ResponseItem] = []

        values = data[6:-4]
        self.__log(f"data complete, parsing... {values}")

        segment_length = 4
        split_values = [values[y - segment_length:y] for y in range(segment_length, len(values) + segment_length, segment_length)]

        for id, value in enumerate(split_values):
            item = request_items[id]

            if not item.skip:
                dec_value = common.s16(int(value, 16)) / item.multiplier
                response_data.append(ResponseItem(item.description, dec_value, item.unit))

        return response_data

    async def __connect_to_device(self, connection_timeout=2000) -> aioble.central.DeviceConnection | None:
        connection = None
        device = aioble.Device(aioble.ADDR_PUBLIC, self.device_address)

        try:
            connection = await device.connect(timeout_ms=connection_timeout)
        except asyncio.TimeoutError:
            self.__log(f"timeout while connecting to {self.device_address}")

        return connection

    def __log(self, message: str):
        if self.logging:
            print(message)
