class LicenseTests(WarehouseTestCase):
    MACHINE = "ABCD-EFGH-JKMN"

    def setUp(self):
        super().setUp()
        self.private_key = Ed25519PrivateKey.generate()
        self.public_hex = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
        self.licensing = Licensing(self.conn, self.MACHINE, self.public_hex)

    def key(self, expires=None, machine=MACHINE, firm="Temir Savdo MChJ", private_key=None):
        return create_license(private_key or self.private_key, License(firm, machine, expires, TODAY))

    def test_machine_code_is_stable_and_readable(self):
        self.assertEqual(machine_code(), machine_code())
        self.assertRegex(machine_code(), r"^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")

    def test_round_trip(self):
        license = parse_license(self.key(date(2027, 10, 3)), self.public_hex)
        self.assertEqual((license.firm, license.machine, license.expires), ("Temir Savdo MChJ", self.MACHINE, date(2027, 10, 3)))

    def test_tampered_or_foreign_key_is_rejected(self):
        key = self.key()
        prefix, payload, signature = key.split(".")
        forged = create_license(Ed25519PrivateKey.generate(), License("Boshqa", self.MACHINE, None, TODAY))
        for bad in (f"{prefix}.{payload[:-2]}AA.{signature}", forged, "MME1.abc", "", "salom"):
            with self.assertRaises(WarehouseError):
                parse_license(bad, self.public_hex)

    def test_key_survives_line_breaks_and_spaces(self):
        key = self.key()
        wrapped = "\n".join(key[i : i + 40] for i in range(0, len(key), 40)) + "  "
        self.assertEqual(self.licensing.activate(wrapped, TODAY).status, LicenseStatus.ACTIVE)

    def test_trial_then_read_only(self):
        state = self.licensing.state(TODAY)
        self.assertEqual((state.status, state.days_left, state.read_only), (LicenseStatus.TRIAL, 14, False))
        self.assertEqual(self.licensing.state(TODAY + timedelta(days=13)).days_left, 1)
        expired = self.licensing.state(TODAY + timedelta(days=14))
        self.assertEqual((expired.status, expired.read_only), (LicenseStatus.EXPIRED, True))

    def test_activation_with_expiry(self):
        state = self.licensing.activate(self.key(TODAY + timedelta(days=30)), TODAY)
        self.assertEqual((state.status, state.firm, state.days_left), (LicenseStatus.ACTIVE, "Temir Savdo MChJ", 31))
        self.assertEqual(self.licensing.state(TODAY + timedelta(days=30)).status, LicenseStatus.ACTIVE)
        after = self.licensing.state(TODAY + timedelta(days=31))
        self.assertEqual((after.status, after.firm, after.read_only), (LicenseStatus.EXPIRED, "Temir Savdo MChJ", True))

    def test_perpetual_license(self):
        state = self.licensing.activate(self.key(), TODAY)
        self.assertEqual((state.status, state.days_left, state.needs_attention), (LicenseStatus.ACTIVE, None, False))
        self.assertEqual(self.licensing.state(TODAY + timedelta(days=5000)).status, LicenseStatus.ACTIVE)

    def test_key_for_another_computer_is_rejected(self):
        with self.assertRaises(WarehouseError) as raised:
            self.licensing.activate(self.key(machine="ZZZZ-ZZZZ-ZZZZ"), TODAY)
        self.assertIn(self.MACHINE, str(raised.exception))
        self.assertEqual(self.licensing.state(TODAY).status, LicenseStatus.TRIAL)

    def test_expired_key_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.licensing.activate(self.key(TODAY - timedelta(days=1)), TODAY)

    def test_database_copied_to_another_computer_loses_license(self):
        self.licensing.activate(self.key(), TODAY)
        elsewhere = Licensing(self.conn, "ZZZZ-ZZZZ-ZZZZ", self.public_hex)
        self.assertEqual(elsewhere.state(TODAY).status, LicenseStatus.TRIAL)

    def test_turning_the_clock_back_does_not_extend_trial(self):
        self.licensing.state(TODAY)
        self.assertTrue(self.licensing.state(TODAY + timedelta(days=20)).read_only)
        self.assertTrue(self.licensing.state(TODAY).read_only)

    def test_real_public_key_rejects_test_keys(self):
        with self.assertRaises(WarehouseError):
            Licensing(self.conn, self.MACHINE).activate(self.key(), TODAY)


