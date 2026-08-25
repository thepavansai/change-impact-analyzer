package com.shop.api;

import com.shop.model.Customer;
import com.shop.service.CustomerService;

public class CustomerApi {

    private CustomerService customerService = new CustomerService();

    public String getCustomer(String id) {
        Customer customer = customerService.findCustomer(id);
        // Public API response contract: email is serialized directly into JSON.
        return "{ \"email\": \"" + customer.getEmail() + "\" }";
    }
}
