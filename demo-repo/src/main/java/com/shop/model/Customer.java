package com.shop.model;

import java.util.Optional;

public class Customer {
    private Optional<String> email;
    private String name;

    public Optional<String> getEmail() {
        return email;
    }

    public void setEmail(Optional<String> email) {
        this.email = email;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }
}