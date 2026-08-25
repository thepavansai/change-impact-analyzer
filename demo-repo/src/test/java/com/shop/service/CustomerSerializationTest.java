package com.shop.service;

import com.shop.model.Customer;

public class CustomerSerializationTest {

    public void testEmailSerialization() {
        Customer customer = new Customer();
        customer.setEmail("serialize@example.com");
        String email = customer.getEmail();
        assert email.length() > 0;
    }
}
