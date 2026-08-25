package com.shop.service;

import com.shop.api.CustomerApi;

public class CustomerApiTest {

    public void testGetCustomer() {
        CustomerApi api = new CustomerApi();
        String json = api.getCustomer("123");
        assert json.contains("email");
    }
}
