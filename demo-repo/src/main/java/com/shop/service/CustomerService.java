package com.shop.service;

import com.shop.model.Customer;

public class CustomerService {

    public Customer findCustomer(String id) {
        Customer customer = new Customer();
        customer.setEmail("customer@example.com");
        customer.setName("Jane Doe");
        return customer;
    }

    public String getCustomerEmail(Customer customer) {
        return customer.getEmail();
    }
}
