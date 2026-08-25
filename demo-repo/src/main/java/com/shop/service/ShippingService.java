package com.shop.service;

import com.shop.model.Customer;

public class ShippingService {

    // NEGATIVE CONTROL: depends on Customer, but only on getName() — NOT email.
    // A correct analyzer must NOT flag this when only `email` changes.
    public String label(Customer customer) {
        return "Ship to: " + customer.getName();
    }
}
