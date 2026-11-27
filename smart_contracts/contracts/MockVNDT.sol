// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Test-only VNDT token. It is not a fiat-backed stablecoin.
contract MockVNDT is ERC20, Ownable {
    constructor() ERC20("Mock Vietnamese Dong Token", "mVNDT") Ownable(msg.sender) {}

    function mint(address to, uint256 amount) external onlyOwner {
        require(to != address(0), "zero recipient");
        _mint(to, amount);
    }
}
