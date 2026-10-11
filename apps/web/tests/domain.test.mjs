import test from "node:test";
import assert from "node:assert/strict";
import { chooseMerchantShop } from "../src/domain.js";

test("merchant opens the last selected owned store across management views", () => {
  const shops = [
    { id: 41, status: "approved", reviewCount: 0 },
    { id: 1, status: "approved", reviewCount: 12 },
  ];
  assert.equal(chooseMerchantShop(shops, 41), 41);
  assert.equal(chooseMerchantShop(shops, 999), 1);
});
test("merchant defaults to an approved store with feedback while new admissions remain manageable", () => {
  assert.equal(
    chooseMerchantShop([
      { id: 7, status: "pending", reviewCount: 0 },
      { id: 41, status: "approved", reviewCount: 0 },
      { id: 1, status: "approved", reviewCount: 12 },
    ]),
    1,
  );
  assert.equal(
    chooseMerchantShop([{ id: 7, status: "pending", reviewCount: 0 }]),
    7,
  );
  assert.equal(chooseMerchantShop([]), null);
});
