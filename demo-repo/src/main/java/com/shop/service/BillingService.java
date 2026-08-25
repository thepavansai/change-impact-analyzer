package com.shop.service;

import com.shop.model.Customer;

public class BillingService {

    private InvoiceService invoiceService = new InvoiceService();

    public String charge(Customer customer, double amount) {
        // Assumes email is present so it can send the receipt.
        String email = customer.getEmail();
        String invoice = invoiceService.generateInvoice(customer, amount);
        return "Charged " + email + " -> " + invoice;
    }
}
