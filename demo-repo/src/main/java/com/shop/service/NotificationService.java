package com.shop.service;

import com.shop.model.Customer;

public class NotificationService {

    public void sendWelcome(Customer customer) {
        // Expects a plain String and calls .trim() on it directly.
        String to = customer.getEmail();
        System.out.println("Sending welcome email to " + to.trim());
    }
}
