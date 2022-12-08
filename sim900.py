from binascii import hexlify
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from operator import truth
from sys import argv
from time import sleep

from gsmmodem.pdu import EncodingError, decodeSmsPdu, encodeSmsSubmitPdu
from serial import Serial


@dataclass(slots=True, frozen=True)
class Call:
    phone: str
    ts: datetime

    def __init__(self, phone: str, ts: datetime | None = None) -> None:
        object.__setattr__(self, "phone", phone)
        date = datetime.now() if ts is None else ts
        object.__setattr__(self, "ts", date)

    def __iter__(self):
        for i in (("phone", self.phone), ("ts", self.ts.isoformat())):
            yield i


@dataclass(slots=True, frozen=True)
class Message:
    phone: str
    ts: datetime
    text: str

    def __iter__(self):
        for i in (
            ("phone", self.phone),
            ("ts", self.ts.isoformat()),
            ("text", self.text),
        ):
            yield i


class AdditionMessages:
    def __init__(self) -> None:
        self.m = defaultdict(dict)

    def __call__(self, msg) -> Message | None:
        try:
            m = decodeSmsPdu(msg)
            if d := m.get("udh"):
                self.m[d[0].reference][d[0].number] = m["text"]
                if len(self.m[d[0].reference].keys()) == d[0].parts:
                    t = self.m.pop(d[0].reference)
                    text = "".join(t[i] for i in sorted(t.keys()))
                    return Message(m["number"], m["time"], text)
                else:
                    return None
            else:
                return Message(m["number"], m["time"], m["text"])

        except EncodingError:
            pass


class Sim900Error(Exception):
    def __init__(self, r: bytes | None = b""):
        if isinstance(r, bytes):
            msg = f'Error run command: {r.decode("utf-8")}'
        else:
            msg = f"Error run command: {r}"
        super().__init__(msg)


class Sim900NoResponse(Exception):
    def __init__(self):
        super().__init__(
            "There is no response from device, "
            "check the connection or the response timeout"
        )


def decode(st: str) -> str:
    r = ""
    for i in range(int(len(st) / 4)):
        a = i * 4
        r += chr(int(st[a: a + 4], 16))
    return r


def encode(st: str) -> str:
    return hexlify(st.encode("utf-16-be")).decode("utf-8").upper()


def parser_read(st: bytes) -> tuple[str]:
    if isinstance(st, bytes):
        return tuple(filter(truth, st.decode("utf-8").split("\r\n")))
    else:
        return tuple(st)


class Sim900:
    def __init__(self, tty="/dev/ttyAMA0", speed=19200) -> None:
        self.serial = Serial
        self._connect = self.serial(tty, speed)
        self.tty: str = tty
        self.speed: int = speed
        self.status: bool = False
        self.time_response: int = 3
        self.buffer: bytes | None = None
        self.auto_del_message = True
        self.operator: str | None = None
        self.rssi: str | None = None
        self.ber: str | None = None
        self.npd: bool = False  # Normal power down
        self.dev: str | None = None
        self.rev: str | None = None
        self._a = AdditionMessages()  # sms processing
        self._many_sms: bool = False
        self._task_queue: deque = deque()

    def connect(self):
        self._connect = self.serial(self.tty, self.speed)
        self.status = True

    def read(self) -> tuple[str]:
        self.buffer = self._connect.read_all()
        return parser_read(self.buffer)

    def parser_command(self, data: tuple[str]) -> tuple[str]:
        self.checking_incoming_data(data)
        if len(data) == 0:
            raise Sim900NoResponse
        elif data[-1] == "ERROR":
            raise Sim900Error(self.buffer)
        else:
            return data[1:-1]

    def command(self, command: str) -> int | None:
        return self._connect.write(bytes(command + "\r", "utf-8"))

    def send_command(self, command: str) -> tuple:
        self.command(command)
        sleep(self.time_response)
        return self.parser_command(self.read())

    def get_operator(self) -> str:
        c = self.send_command("AT+COPS?")[0]
        self.operator = c.split(",")[-1].replace('"', "")
        return self.operator

    def get_csq(self) -> None:
        """
        <rssi>
        0 -115 dBm or less
        1 -111 dBm
        2...30 -110... -54 dBm
        31 -52 dBm or greater
        99 not known or not detectable

        <ber> (in percent):
        0...7 As RXQUAL values in the table in GSM 05.08 [20] subclause 7.2.4
        99 Not known or not detectable
        """
        c = self.send_command("AT+CSQ")[0]
        self.rssi, self.ber = c.split()[-1].split(",")

    def get_product_info(self) -> str:
        self.dev = self.send_command("ATI")[0]
        return self.dev

    def get_revision(self) -> str:
        self.rev = self.send_command("AT+GMR")[0]
        return self.rev

    def checking_status_board(self):
        self.get_product_info()
        self.get_revision()
        self.get_operator()
        self.get_csq()

    def pre_up(self) -> None:
        self._connect.read_all()
        self.send_command("AT")
        self.checking_status_board()
        # calling line identification presentation
        self.send_command("AT+CLIP=1")
        # set PDU mode
        self.send_command("AT+CMGF=0")

    def get_all_sms_message(self) -> list[Message]:
        ms = self.send_command("AT+CMGL=4")
        msg = [m for i in range(1, len(ms), 2) if (m := self._a(ms[i]))]
        if self.auto_del_message:
            self.send_command("AT+CMGD=1,4")
        return msg

    def send_sms(self, phone: str, text: str) -> None:
        for m in encodeSmsSubmitPdu(phone, text):
            self.command(f"AT+CMGS={m.tpduLength}")
            sleep(0.5)
            self._connect.write(bytes(str(m), "utf-8"))
            sleep(0.5)
            self.send_command(chr(26))

    def send_ussd(self, ussd: str) -> None:
        self.send_command(f'AT+CUSD=1,"{encode(ussd)}"')

    def call(self, phone: str) -> None:
        """
        Phone example: +12345678900
        """
        self.send_command(f"ATD{phone};")

    def del_sms(self, sms_id: int) -> None:
        self.send_command(f"AT+CMGD={sms_id}")

    def get_sms(self, sms_id: int) -> Message | None:
        msg = self._a(self.send_command(f"AT+CMGR={sms_id}")[1])
        if self.auto_del_message:
            self.del_sms(sms_id)
        return msg

    def hung_up_call(self):
        return self.command("ATH")

    def additional_function_message(self, msg: Message) -> None:
        pass

    def additional_function_call(self, call: Call) -> None:
        pass

    def incoming_call(self, data: tuple[str]) -> None:
        self.hung_up_call()
        for d in filter(lambda x: "CLIP:" in x, data):
            phone = d.replace('"', "").split(",")[0].split()[1]
            c = Call(phone=phone)
            self.additional_function_call(c)

    def __incoming_sms(self, sms_id: int) -> None:
        msg = self.get_sms(sms_id)
        if msg:
            self._task_queue.append((self.additional_function_message, (msg,)))

    def incoming_message(self, data: tuple[str]) -> None:
        for d in filter(lambda x: '+CMTI: "SM"' in x, data):
            sms_id = int(d.split(",")[1])
            if sms_id > 0:
                self._many_sms = True
            self._task_queue.append((self.__incoming_sms, (sms_id,)))

    def incoming_ussd(self, data: tuple[str]) -> None:
        for d in filter(lambda x: "CUSD:" in x, data):
            msg = Message(
                phone="USSD",
                ts=datetime.now(),
                text=decode(d.split(",")[1].replace('"', "")),
            )
            self._task_queue.append((self.additional_function_message, (msg,)))

    def checking_incoming_data(self, st: tuple[str]) -> bool:
        def checking(f: str, ls: tuple[str]) -> bool:
            return any(map(lambda x: True if f in x else False, ls))

        if checking("RING", st):
            self.incoming_call(st)

        if checking("CUSD:", st):
            self.incoming_ussd(st)

        if checking('+CMTI: "SM"', st):
            self.incoming_message(st)

        if checking("NORMAL POWER DOWN", st):
            self.npd = True
            self.status = False
            return True
        return False

    def run_task(self) -> bool:
        try:
            task = self._task_queue.popleft()
            task[0](*task[1])
            return True
        except IndexError:
            return False

    def run(self):
        while self.npd is False:
            while len(self._task_queue) > 0:
                self.run_task()
            if self._connect.in_waiting > 0:
                if self.checking_incoming_data(self.read()):
                    break
            sleep(0.5)


def simple_start(tty="/dev/ttyUSB0", speed: str | int = 19200) -> Sim900:
    s9 = Sim900(tty=tty, speed=int(speed))
    s9.connect()
    s9.pre_up()
    return s9


if __name__ == "__main__":
    s = simple_start(*argv[1:])
    s.run()
