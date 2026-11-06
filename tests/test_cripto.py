import unittest

from portal import cripto


class CriptoTest(unittest.TestCase):
    def test_hash_y_verificacion(self):
        almacenado = cripto.hash_password("Porto2026*")
        self.assertTrue(almacenado.startswith("scrypt$"))
        self.assertTrue(cripto.verify_password("Porto2026*", almacenado))

    def test_password_incorrecta(self):
        almacenado = cripto.hash_password("Porto2026*")
        self.assertFalse(cripto.verify_password("otra-clave", almacenado))

    def test_hash_malformado(self):
        self.assertFalse(cripto.verify_password("x", "no-es-un-hash"))
        self.assertFalse(cripto.verify_password("x", "scrypt$1$2$3$invalido"))

    def test_tokens_distintos(self):
        self.assertNotEqual(cripto.token(), cripto.token())
        self.assertGreaterEqual(len(cripto.token(16)), 16)


if __name__ == "__main__":
    unittest.main()
