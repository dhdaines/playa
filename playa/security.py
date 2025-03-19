"""PDF "security" handlers."""

import struct
from hashlib import md5, sha256, sha384, sha512
from typing import (
    Any,
    Callable,
    Dict,
    Optional,
    Sequence,
    Tuple,
)

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    default_backend = None  # type: ignore

from playa.arcfour import Arcfour
from playa.exceptions import (
    PDFEncryptionError,
    PDFPasswordIncorrect,
)
from playa.pdftypes import (
    dict_value,
    int_value,
    literal_name,
    str_value,
    uint_value,
)

PASSWORD_PADDING = (
    b"(\xbfN^Nu\x8aAd\x00NV\xff\xfa\x01\x08" b"..\x00\xb6\xd0h>\x80/\x0c\xa9\xfedSiz"
)


class PDFStandardSecurityHandler:
    """Basic security handler for basic encryption types."""

    supported_revisions: Tuple[int, ...] = (2, 3)

    def __init__(
        self,
        docid: Sequence[bytes],
        param: Dict[str, Any],
        password: str = "",
    ) -> None:
        self.docid = docid
        self.param = param
        self.password = password
        self.init()

    def init(self) -> None:
        self.init_params()
        if self.r not in self.supported_revisions:
            error_msg = "Unsupported revision: param=%r" % self.param
            raise PDFEncryptionError(error_msg)
        self.init_key()

    def init_params(self) -> None:
        self.v = int_value(self.param.get("V", 0))
        self.r = int_value(self.param["R"])
        self.p = uint_value(self.param["P"], 32)
        self.o = str_value(self.param["O"])
        self.u = str_value(self.param["U"])
        self.length = int_value(self.param.get("Length", 40))

    def init_key(self) -> None:
        self.key = self.authenticate(self.password)
        if self.key is None:
            raise PDFPasswordIncorrect

    @property
    def is_printable(self) -> bool:
        return bool(self.p & 4)

    @property
    def is_modifiable(self) -> bool:
        return bool(self.p & 8)

    @property
    def is_extractable(self) -> bool:
        return bool(self.p & 16)

    def compute_u(self, key: bytes) -> bytes:
        if self.r == 2:
            # Algorithm 3.4
            return Arcfour(key).encrypt(PASSWORD_PADDING)  # 2
        else:
            # Algorithm 3.5
            hash = md5(PASSWORD_PADDING)  # 2
            hash.update(self.docid[0])  # 3
            result = Arcfour(key).encrypt(hash.digest())  # 4
            for i in range(1, 20):  # 5
                k = b"".join(bytes((c ^ i,)) for c in iter(key))
                result = Arcfour(k).encrypt(result)
            result += result  # 6
            return result

    def compute_encryption_key(self, password: bytes) -> bytes:
        # Algorithm 3.2
        password = (password + PASSWORD_PADDING)[:32]  # 1
        hash = md5(password)  # 2
        hash.update(self.o)  # 3
        # See https://github.com/pdfminer/pdfminer.six/issues/186
        hash.update(struct.pack("<L", self.p))  # 4
        hash.update(self.docid[0])  # 5
        if self.r >= 4:
            assert isinstance(self, PDFStandardSecurityHandlerV4)
            if not self.encrypt_metadata:
                hash.update(b"\xff\xff\xff\xff")
        result = hash.digest()
        n = 5
        if self.r >= 3:
            n = self.length // 8
            for _ in range(50):
                result = md5(result[:n]).digest()
        return result[:n]

    def authenticate(self, password: str) -> Optional[bytes]:
        password_bytes = password.encode("latin1")
        key = self.authenticate_user_password(password_bytes)
        if key is None:
            key = self.authenticate_owner_password(password_bytes)
        return key

    def authenticate_user_password(self, password: bytes) -> Optional[bytes]:
        key = self.compute_encryption_key(password)
        if self.verify_encryption_key(key):
            return key
        else:
            return None

    def verify_encryption_key(self, key: bytes) -> bool:
        # Algorithm 3.6
        u = self.compute_u(key)
        if self.r == 2:
            return u == self.u
        return u[:16] == self.u[:16]

    def authenticate_owner_password(self, password: bytes) -> Optional[bytes]:
        # Algorithm 3.7
        password = (password + PASSWORD_PADDING)[:32]
        hash = md5(password)
        if self.r >= 3:
            for _ in range(50):
                hash = md5(hash.digest())
        n = 5
        if self.r >= 3:
            n = self.length // 8
        key = hash.digest()[:n]
        if self.r == 2:
            user_password = Arcfour(key).decrypt(self.o)
        else:
            user_password = self.o
            for i in range(19, -1, -1):
                k = b"".join(bytes((c ^ i,)) for c in iter(key))
                user_password = Arcfour(k).decrypt(user_password)
        return self.authenticate_user_password(user_password)

    def decrypt(
        self,
        objid: int,
        genno: int,
        data: bytes,
        attrs: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        return self.decrypt_rc4(objid, genno, data)

    def decrypt_rc4(self, objid: int, genno: int, data: bytes) -> bytes:
        assert self.key is not None
        key = self.key + struct.pack("<L", objid)[:3] + struct.pack("<L", genno)[:2]
        hash = md5(key)
        key = hash.digest()[: min(len(key), 16)]
        return Arcfour(key).decrypt(data)


class PDFStandardSecurityHandlerV4(PDFStandardSecurityHandler):
    """Security handler for encryption type 4."""

    supported_revisions: Tuple[int, ...] = (4,)

    def __init__(self, *args, **kwargs) -> None:
        if default_backend is None:
            raise PDFEncryptionError(
                "Encryption type requires the "
                "optional `cryptography` package. "
                "You may install it with `pip install playa-pdf[crypto]`."
            )
        super().__init__(*args, **kwargs)

    def init_params(self) -> None:
        super().init_params()
        self.length = 128
        self.cf = dict_value(self.param.get("CF"))
        self.stmf = literal_name(self.param["StmF"])
        self.strf = literal_name(self.param["StrF"])
        self.encrypt_metadata = bool(self.param.get("EncryptMetadata", True))
        if self.stmf != self.strf:
            error_msg = "Unsupported crypt filter: param=%r" % self.param
            raise PDFEncryptionError(error_msg)
        self.cfm = {}
        for k, v in self.cf.items():
            dictv = dict_value(v)
            f = self.get_cfm(literal_name(dictv["CFM"]))
            if f is None:
                error_msg = "Unknown crypt filter method: param=%r" % self.param
                raise PDFEncryptionError(error_msg)
            self.cfm[k] = f
        self.cfm["Identity"] = self.decrypt_identity
        if self.strf not in self.cfm:
            error_msg = "Undefined crypt filter: param=%r" % self.param
            raise PDFEncryptionError(error_msg)

    def get_cfm(self, name: str) -> Optional[Callable[[int, int, bytes], bytes]]:
        if name == "V2":
            return self.decrypt_rc4
        elif name == "AESV2":
            return self.decrypt_aes128
        else:
            return None

    def decrypt(
        self,
        objid: int,
        genno: int,
        data: bytes,
        attrs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> bytes:
        if not self.encrypt_metadata and attrs is not None:
            t = attrs.get("Type")
            if t is not None and literal_name(t) == "Metadata":
                return data
        if name is None:
            name = self.strf
        return self.cfm[name](objid, genno, data)

    def decrypt_identity(self, objid: int, genno: int, data: bytes) -> bytes:
        return data

    def decrypt_aes128(self, objid: int, genno: int, data: bytes) -> bytes:
        assert self.key is not None
        key = (
            self.key
            + struct.pack("<L", objid)[:3]
            + struct.pack("<L", genno)[:2]
            + b"sAlT"
        )
        hash = md5(key)
        key = hash.digest()[: min(len(key), 16)]
        initialization_vector = data[:16]
        ciphertext = data[16:]
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(initialization_vector),
            backend=default_backend(),
        )  # type: ignore
        return cipher.decryptor().update(ciphertext)  # type: ignore


class PDFStandardSecurityHandlerV5(PDFStandardSecurityHandlerV4):
    """Security handler for encryption types 5 and 6."""

    supported_revisions = (5, 6)

    def __init__(self, *args, **kwargs) -> None:
        if default_backend is None:
            raise PDFEncryptionError(
                "Encryption type requires the "
                "optional `cryptography` package. "
                "You may install it with playa[crypto]."
            )
        super().__init__(*args, **kwargs)

    def init_params(self) -> None:
        super().init_params()
        self.length = 256
        self.oe = str_value(self.param["OE"])
        self.ue = str_value(self.param["UE"])
        self.o_hash = self.o[:32]
        self.o_validation_salt = self.o[32:40]
        self.o_key_salt = self.o[40:]
        self.u_hash = self.u[:32]
        self.u_validation_salt = self.u[32:40]
        self.u_key_salt = self.u[40:]

    def get_cfm(self, name: str) -> Optional[Callable[[int, int, bytes], bytes]]:
        if name == "AESV3":
            return self.decrypt_aes256
        else:
            return None

    def authenticate(self, password: str) -> Optional[bytes]:
        password_b = self._normalize_password(password)
        hash = self._password_hash(password_b, self.o_validation_salt, self.u)
        if hash == self.o_hash:
            hash = self._password_hash(password_b, self.o_key_salt, self.u)
            cipher = Cipher(
                algorithms.AES(hash),
                modes.CBC(b"\0" * 16),
                backend=default_backend(),
            )  # type: ignore
            return cipher.decryptor().update(self.oe)  # type: ignore
        hash = self._password_hash(password_b, self.u_validation_salt)
        if hash == self.u_hash:
            hash = self._password_hash(password_b, self.u_key_salt)
            cipher = Cipher(
                algorithms.AES(hash),
                modes.CBC(b"\0" * 16),
                backend=default_backend(),
            )  # type: ignore
            return cipher.decryptor().update(self.ue)  # type: ignore
        return None

    def _normalize_password(self, password: str) -> bytes:
        if self.r == 6:
            # saslprep expects non-empty strings, apparently
            if not password:
                return b""
            from playa._saslprep import saslprep

            password = saslprep(password)
        return password.encode("utf-8")[:127]

    def _password_hash(
        self,
        password: bytes,
        salt: bytes,
        vector: Optional[bytes] = None,
    ) -> bytes:
        """Compute password hash depending on revision number"""
        if self.r == 5:
            return self._r5_password(password, salt, vector)
        return self._r6_password(password, salt[0:8], vector)

    def _r5_password(
        self,
        password: bytes,
        salt: bytes,
        vector: Optional[bytes] = None,
    ) -> bytes:
        """Compute the password for revision 5"""
        hash = sha256(password)
        hash.update(salt)
        if vector is not None:
            hash.update(vector)
        return hash.digest()

    def _r6_password(
        self,
        password: bytes,
        salt: bytes,
        vector: Optional[bytes] = None,
    ) -> bytes:
        """Compute the password for revision 6"""
        initial_hash = sha256(password)
        initial_hash.update(salt)
        if vector is not None:
            initial_hash.update(vector)
        k = initial_hash.digest()
        hashes = (sha256, sha384, sha512)
        round_no = last_byte_val = 0
        while round_no < 64 or last_byte_val > round_no - 32:
            k1 = (password + k + (vector or b"")) * 64
            e = self._aes_cbc_encrypt(key=k[:16], iv=k[16:32], data=k1)
            # compute the first 16 bytes of e,
            # interpreted as an unsigned integer mod 3
            next_hash = hashes[self._bytes_mod_3(e[:16])]
            k = next_hash(e).digest()
            last_byte_val = e[len(e) - 1]
            round_no += 1
        return k[:32]

    @staticmethod
    def _bytes_mod_3(input_bytes: bytes) -> int:
        # 256 is 1 mod 3, so we can just sum 'em
        return sum(b % 3 for b in input_bytes) % 3

    def _aes_cbc_encrypt(self, key: bytes, iv: bytes, data: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()  # type: ignore
        return encryptor.update(data) + encryptor.finalize()  # type: ignore

    def decrypt_aes256(self, objid: int, genno: int, data: bytes) -> bytes:
        initialization_vector = data[:16]
        ciphertext = data[16:]
        assert self.key is not None
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(initialization_vector),
            backend=default_backend(),
        )  # type: ignore
        return cipher.decryptor().update(ciphertext)  # type: ignore


SECURITY_HANDLERS = {
    1: PDFStandardSecurityHandler,
    2: PDFStandardSecurityHandler,
    4: PDFStandardSecurityHandlerV4,
    5: PDFStandardSecurityHandlerV5,
}
