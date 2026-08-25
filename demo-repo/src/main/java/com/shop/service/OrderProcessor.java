package com.shop.service;

import com.shop.model.Customer;

public class OrderProcessor {

    private BillingService billingService = new BillingService();

    // TRANSITIVE CASE: does not touch email itself, but calls
    // BillingService.charge(), which does. Should be flagged at depth 2.
    public String placeOrder(Customer customer, double amount) {
        return billingService.charge(customer, amount);
    }
}
